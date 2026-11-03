import os
import sys
import json
import csv
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import re
import html
import shutil
import subprocess

# 설정 및 기본 경로
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

# 공유용 공식 마스킹 URL (개인 깃허브 계정 노출 방지용 단축링크)
PUBLIC_MASKED_URL = "https://tr.ee/Z51VtU"
# 실제 내부 호스팅 URL (배포 목적지 - 외부에 노출하지 않음)
INTERNAL_HOSTING_URL = "https://hellouou.github.io/briefing/"
# 핸드폰 알림 채널명 (ntfy.sh 앱에서 구독할 채널)
NTFY_TOPIC = "briefing-hellouou"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# 조회할 시장 지표 정의
TICKERS = [
    {"symbol": "^DJI", "name": "다우 존스", "category": "global", "unit": "pt"},
    {"symbol": "^GSPC", "name": "S&P 500", "category": "global", "unit": "pt"},
    {"symbol": "^IXIC", "name": "나스닥", "category": "global", "unit": "pt"},
    {"symbol": "^SOX", "name": "필라델피아 반도체", "category": "global", "unit": "pt"},
    {"symbol": "^KS11", "name": "코스피", "category": "domestic", "unit": "pt"},
    {"symbol": "^KQ11", "name": "코스닥", "category": "domestic", "unit": "pt"},
    {"symbol": "KRW=X", "name": "원/달러 환율", "category": "macro", "unit": "원"},
    {"symbol": "CL=F", "name": "WTI 국제유가", "category": "macro", "unit": "달러"},
    {"symbol": "GC=F", "name": "금 선물", "category": "macro", "unit": "달러"},
    {"symbol": "^TNX", "name": "미국 10년물 국채금리", "category": "macro", "unit": "%"},
    {"symbol": "BTC-USD", "name": "비트코인", "category": "crypto", "unit": "달러"},
]

def clean_text(text):
    if not text:
        return ""
    text = html.unescape(html.unescape(text))
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def fetch_url(url, timeout=7, ua=None):
    try:
        user_agent = ua or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        req = urllib.request.Request(url, headers={'User-Agent': user_agent, 'Referer': 'https://newsstand.naver.com/'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except Exception:
        return ""

# ==========================================
# 증시 및 거시경제 지표 수집
# ==========================================

def fetch_ticker_data(symbol):
    """Yahoo Finance API를 통해 지표 데이터 수집"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice", 0.0)
            prev = meta.get("chartPreviousClose", price)
            diff = price - prev if prev else 0.0
            pct = (diff / prev * 100) if prev else 0.0
            return {
                "price": round(price, 2),
                "diff": round(diff, 2),
                "pct": round(pct, 2),
                "currency": meta.get("currency", "")
            }
    except Exception as e:
        print(f"[{symbol}] 수집 오류: {e}", file=sys.stderr)
        return {"price": 0.0, "diff": 0.0, "pct": 0.0, "currency": ""}

def generate_market_summary(market_data):
    """지수 데이터를 기반으로 자동 시장 요약 생성"""
    ixic = market_data.get("^IXIC", {}).get("pct", 0)
    gspc = market_data.get("^GSPC", {}).get("pct", 0)
    krw = market_data.get("KRW=X", {}).get("price", 0)
    oil = market_data.get("CL=F", {}).get("pct", 0)
    
    notes = []
    if ixic >= 1.0:
        notes.append("미국 기술주 중심의 나스닥 지수가 1% 이상 큰 폭으로 상승 마감했습니다.")
    elif ixic <= -1.0:
        notes.append("미국 나스닥 지수가 1% 이상 하락하며 기술주 중심의 차익 실현 및 경계 심리가 부각되었습니다.")
    else:
        notes.append(f"미국 증시는 S&P 500({gspc:+.2f}%), 나스닥({ixic:+.2f}%) 혼조세/보합권으로 마감했습니다.")

    if krw > 1350:
        notes.append(f"원/달러 환율이 {krw:,.2f}원대로 높은 수준을 기록하고 있습니다.")
    else:
        notes.append(f"원/달러 환율은 {krw:,.2f}원 수준을 기록하고 있습니다.")

    if oil >= 3.0:
        notes.append(f"국제 유가(WTI)가 {oil:+.2f}% 급등세를 보였습니다.")
    elif oil <= -3.0:
        notes.append(f"국제 유가(WTI)가 {oil:+.2f}% 급락세를 보였습니다.")
        
    return " ".join(notes)

# ==========================================
# 네이버 뉴스스탠드 기반 전면 기사 정밀 추출기
# ==========================================

def extract_article_details(url):
    """기사 원문 페이지에서 헤드라인, 소제목, 주요내용(본문 요약) 및 전문 단락 정밀 추출"""
    art_html = fetch_url(url)
    if not art_html:
        return {"headline": "", "subtitle": "", "summary": "", "paragraphs": []}

    # 1. 헤드라인
    m_title = re.search(r'<meta property="og:title" content="([^"]+)"', art_html)
    title = clean_text(m_title.group(1)) if m_title else ""
    title = re.sub(r'\s*-\s*(경향신문|매일경제|한국경제|한경닷컴).*$', '', title).strip()

    # 2. 소제목 (Subtitle)
    subtitle = ""
    m_hk_sub = re.search(r'<h[23][^>]*class="[^"]*hk_sub_headline[^"]*"[^>]*>(.*?)</h[23]>', art_html, re.DOTALL)
    if m_hk_sub:
        subtitle = clean_text(m_hk_sub.group(1))
    
    if not subtitle:
        m_mid = re.search(r'<div[^>]*class="[^"]*midtitle_text[^"]*"[^>]*>(.*?)</div>', art_html, re.DOTALL)
        if m_mid:
            subtitle = clean_text(m_mid.group(1))
            
    if not subtitle:
        m_sub = re.search(r'<(?:h2|h3|h4|strong|div|p)[^>]*class="[^"]*(?:sub_title|subhead|sub_tit|subtitle|art_sub|art_subtitle|sub-title)[^"]*"[^>]*>(.*?)</(?:h2|h3|h4|strong|div|p)>', art_html, re.DOTALL | re.IGNORECASE)
        if m_sub:
            subtitle = clean_text(m_sub.group(1))

    m_desc = re.search(r'<meta property="og:description" content="([^"]+)"', art_html)
    desc_val = clean_text(m_desc.group(1)) if m_desc else ""
    if not subtitle and desc_val:
        d_clean = desc_val.replace(title, "").strip(" ,·-")
        subtitle = d_clean[:140] if len(d_clean) > 5 else desc_val[:140]

    # 3. 본문 전체 단락(Paragraphs) 추출
    full_paragraphs = []

    # 3-1. 경향신문 단락
    khan_ps = re.findall(r'<p[^>]*class="[^"]*content_text[^"]*"[^>]*>(.*?)</p>', art_html, re.DOTALL)
    if khan_ps:
        valid_ps = [clean_text(p) for p in khan_ps if len(clean_text(p)) > 15 and not any(k in p for k in ['기자', '저작권', '무단전재', '경향신문', '사진='])]
        if valid_ps:
            full_paragraphs = valid_ps

    # 3-2. 한국경제 단락
    if not full_paragraphs:
        idx_hk = art_html.find('id="articletxt"')
        if idx_hk != -1:
            sub = art_html[idx_hk:]
            sub = sub.split('>', 1)[-1]
            end_hk = len(sub)
            for m in ['class="article-copyright', 'class="article-reply', 'class="article-bottom', 'class="article-tag', 'class="editor_profile']:
                pos = sub.find(m)
                if pos != -1 and pos < end_hk:
                    end_hk = pos
            art_body = sub[:end_hk]
            art_body = re.sub(r'<script[^>]*>.*?</script>', '', art_body, flags=re.DOTALL)
            art_body = re.sub(r'<style[^>]*>.*?</style>', '', art_body, flags=re.DOTALL)
            art_body = re.sub(r'<figure[^>]*>.*?</figure>', '', art_body, flags=re.DOTALL)
            art_body = re.sub(r'<h[1-6][^>]*>.*?</h[1-6]>', '', art_body, flags=re.DOTALL)
            parts = re.split(r'<br\s*/?>|<p[^>]*>|</p>', art_body)
            valid_ps = [clean_text(p) for p in parts if len(clean_text(p)) > 20 and not any(k in p for k in ['기자', '한경닷컴', '무단전재', '저작권'])]
            if valid_ps:
                full_paragraphs = valid_ps

    # 3-3. 매일경제 단락
    if not full_paragraphs:
        idx_mk = art_html.find('itemprop="articleBody"')
        if idx_mk != -1:
            sub_mk = art_html[idx_mk:]
            sub_mk = sub_mk.split('>', 1)[-1]
            end_mk = len(sub_mk)
            for m in ['class="ft_box_wrap', 'class="news_tag_wrap', 'class="reporter_wrap', '<!-- 기자 정보 -->']:
                pos = sub_mk.find(m)
                if pos != -1 and pos < end_mk:
                    end_mk = pos
            art_body = sub_mk[:end_mk]
            art_body = re.sub(r'<script[^>]*>.*?</script>', '', art_body, flags=re.DOTALL)
            art_body = re.sub(r'<figure[^>]*>.*?</figure>', '', art_body, flags=re.DOTALL)
            parts = re.split(r'<br\s*/?>|<p[^>]*>|</p>', art_body)
            valid_ps = [clean_text(p) for p in parts if len(clean_text(p)) > 20 and not any(k in p for k in ['기자', '매일경제', '무단전재', '저작권'])]
            if valid_ps:
                full_paragraphs = valid_ps

    # 3-4. 기타 일반 기사 단락 탐색
    if not full_paragraphs:
        all_ps = re.findall(r'<p[^>]*>(.*?)</p>', art_html, re.DOTALL)
        valid_ps = [clean_text(p) for p in all_ps if len(clean_text(p)) > 30 and not any(k in p for k in ['기자', '저작권', '무단전재', 'copyright'])]
        if valid_ps:
            full_paragraphs = valid_ps

    # 4. 주요 내용 / 요약
    summary = ""
    m_ai = re.search(r'AI 기사요약\s*-->\s*AI 기사요약\s*(.*?)(?:</div>|<button)', art_html, re.DOTALL)
    if m_ai:
        summary = clean_text(m_ai.group(1))
    elif full_paragraphs:
        summary = " ".join(full_paragraphs[:2])[:280] + ("..." if len(" ".join(full_paragraphs[:2])) > 280 else "")
    else:
        summary = desc_val[:280]

    if not full_paragraphs and summary:
        full_paragraphs = [summary]

    return {
        "headline": title,
        "subtitle": subtitle,
        "summary": summary,
        "paragraphs": full_paragraphs
    }

def fetch_newsstand_press(pid, name):
    """네이버 뉴스스탠드(newsstand.naver.com)의 신문별 1면 전면 기사 추출"""
    url = f"https://newsstand.naver.com/include/page/{pid}.html"
    raw_html = fetch_url(url)
    if not raw_html:
        return []
    
    articles = []
    seen_links = set()
    
    for m in re.finditer(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', raw_html, re.DOTALL):
        link = m.group(1).replace('&amp;', '&')
        if any(skip in link for skip in ['cafe.naver', 'naver.com', 'ombs', 'facebook', 'twitter']):
            continue
        if not link.startswith('http'):
            continue
            
        clean_link = link.split('?')[0]
        if clean_link in seen_links:
            continue
            
        inner_text = clean_text(m.group(2))
        if len(inner_text) < 8:
            continue
            
        seen_links.add(clean_link)
        
        details = extract_article_details(link)
        headline = details["headline"] if details["headline"] else inner_text
        art_id = f"art_{pid}_{len(articles)}"
        
        articles.append({
            "id": art_id,
            "press": name,
            "is_top": len(articles) == 0,
            "headline": headline,
            "subtitle": details["subtitle"],
            "summary": details["summary"],
            "paragraphs": details.get("paragraphs", []),
            "link": link
        })
        
        if len(articles) >= 4:
            break
            
    return articles

# ==========================================
# 사설 및 오피니언 추출기
# ==========================================

def fetch_opinions_kyunghyang():
    opinion_list = []
    html_page = fetch_url('https://www.khan.co.kr/opinion/editorial/articles')
    if html_page:
        matches = re.findall(r'<a[^>]+href="(https://www\.khan\.co\.kr/article/(\d+))"[^>]*>(.*?)</a>', html_page, re.DOTALL)
        seen = set()
        for link, art_id, content in matches:
            if art_id in seen:
                continue
            title = clean_text(content)
            if '[사설]' in title or len(title) > 10:
                seen.add(art_id)
                details = extract_article_details(link)
                op_headline = details["headline"] if details["headline"] else title
                op_summary = details["summary"] if details["summary"] else "사설 본문 참조"
                op_paragraphs = details.get("paragraphs", [])
                if not op_paragraphs and op_summary:
                    op_paragraphs = [op_summary]
                
                op_id = f"op_032_{len(opinion_list)}"
                opinion_list.append({
                    "id": op_id,
                    "press": "경향신문",
                    "headline": op_headline,
                    "type": "사설" if "[사설]" in op_headline else "오피니언",
                    "subtitle": details.get("subtitle", ""),
                    "summary": op_summary[:240],
                    "paragraphs": op_paragraphs,
                    "link": link
                })
                if len(opinion_list) >= 3:
                    break
    return opinion_list

def fetch_opinions_hankyung():
    opinion_list = []
    hk_ua = 'Mozilla/5.0'
    xml_op = fetch_url('https://www.hankyung.com/feed/opinion', ua=hk_ua)
    if xml_op:
        try:
            root = ET.fromstring(xml_op)
            all_items = root.findall('.//item')
            editorials = [it for it in all_items if '[사설]' in clean_text(it.find('title').text)]
            columns = [it for it in all_items if '[사설]' not in clean_text(it.find('title').text)]
            target_items = (editorials + columns)[:3]

            for it in target_items:
                title = clean_text(it.find('title').text)
                link = it.find('link').text.strip()
                details = extract_article_details(link)
                op_headline = details["headline"] if details["headline"] else title
                op_summary = details["summary"] if details["summary"] else "사설/칼럼 본문 참조"
                op_paragraphs = details.get("paragraphs", [])
                if not op_paragraphs and op_summary:
                    op_paragraphs = [op_summary]
                    
                op_id = f"op_015_{len(opinion_list)}"
                opinion_list.append({
                    "id": op_id,
                    "press": "한국경제",
                    "headline": op_headline,
                    "type": "사설" if "[사설]" in op_headline else "칼럼/오피니언",
                    "subtitle": details.get("subtitle", ""),
                    "summary": op_summary[:240],
                    "paragraphs": op_paragraphs,
                    "link": link
                })
        except Exception as e:
            print(f"[한경 사설 오류] {e}", file=sys.stderr)
    return opinion_list

def fetch_opinions_maekyung():
    opinion_list = []
    mk_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0'
    html_page = fetch_url('https://www.mk.co.kr/opinion/editorial/', ua=mk_ua)
    if html_page:
        matches = re.findall(r'<a[^>]+href="([^"]*/news/editorial/(\d+))"[^>]*>(.*?)</a>', html_page, re.DOTALL)
        seen = set()
        for link, art_id, content in matches:
            if art_id in seen:
                continue
            seen.add(art_id)
            details = extract_article_details(link)
            full_text = clean_text(content)
            
            if '[사설]' in full_text:
                parts = full_text.split('[사설]', 1)
                title = parts[0].strip() + " [사설]"
            else:
                title = full_text[:60]

            op_headline = details["headline"] if details["headline"] else title
            op_summary = details["summary"] if details["summary"] else "사설 본문 참조"
            op_paragraphs = details.get("paragraphs", [])
            if not op_paragraphs and op_summary:
                op_paragraphs = [op_summary]

            op_id = f"op_009_{len(opinion_list)}"
            opinion_list.append({
                "id": op_id,
                "press": "매일경제",
                "headline": op_headline,
                "type": "사설",
                "subtitle": details.get("subtitle", ""),
                "summary": op_summary[:240],
                "paragraphs": op_paragraphs,
                "link": link
            })
            if len(opinion_list) >= 3:
                break
    return opinion_list

# ==========================================
# 모바일 푸시 알림 & GitHub Pages 자동 배포
# ==========================================

def send_mobile_push(date_str, market_summary, click_url=PUBLIC_MASKED_URL, topic=NTFY_TOPIC):
    """스마트폰에 매일 아침 팝업 푸시 알림 전송 (ntfy.sh 무료 서비스)"""
    try:
        url = f"https://ntfy.sh/{topic}"
        title = f"[{date_str}] Morning Briefing"
        headers = {
            "Title": title,
            "Priority": "high",
            "Tags": "chart_with_upwards_trend,newspaper",
            "Click": click_url,
            "Actions": f"view, Open Web Dashboard, {click_url}"
        }
        body = f"📊 [{date_str}] 일일 경제·증시 & 신문 1면 브리핑\n\n{market_summary}\n\n👉 링크: {click_url}".encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                print(f"📱 스마트폰 팝업 푸시 전송 완료! (구독 채널: {topic})")
    except Exception as e:
        print(f"[푸시 알림 전송 참고] {e}", file=sys.stderr)

def sync_to_github_pages(date_str):
    """GitHub Pages에 자동 동기화 및 푸시 (독립된 briefing 저장소 자체 푸시)"""
    if os.path.exists(os.path.join(BASE_DIR, ".git")):
        try:
            subprocess.run(["git", "add", "index.html", "latest_briefing.md", "history.csv", "data", "reports"], cwd=BASE_DIR, check=True)
            subprocess.run(["git", "commit", "-m", f"Auto-update morning briefing ({date_str})"], cwd=BASE_DIR, capture_output=True)
            res = subprocess.run(["git", "push", "origin", "main"], cwd=BASE_DIR, capture_output=True, text=True)
            if res.returncode == 0:
                print(f"🌐 GitHub Pages 웹 호스팅 배포 완료: {INTERNAL_HOSTING_URL} (공개 단축링크: {PUBLIC_MASKED_URL})")
                return PUBLIC_MASKED_URL
            else:
                print(f"[Git 푸시 알림] {res.stderr.strip()}", file=sys.stderr)
        except Exception as e:
            print(f"[GitHub 배포 알림] {e}", file=sys.stderr)
    return PUBLIC_MASKED_URL

def save_csv_history(now_str, market_data):
    """history.csv에 일별 핵심 데이터 누적"""
    csv_file = os.path.join(BASE_DIR, "history.csv")
    headers = ["date", "kospi", "kosdaq", "sp500", "nasdaq", "dow", "sox", "usdkrw", "wti", "gold", "us10y", "btc"]
    row = [
        now_str,
        market_data.get("^KS11", {}).get("price", ""),
        market_data.get("^KQ11", {}).get("price", ""),
        market_data.get("^GSPC", {}).get("price", ""),
        market_data.get("^IXIC", {}).get("price", ""),
        market_data.get("^DJI", {}).get("price", ""),
        market_data.get("^SOX", {}).get("price", ""),
        market_data.get("KRW=X", {}).get("price", ""),
        market_data.get("CL=F", {}).get("price", ""),
        market_data.get("GC=F", {}).get("price", ""),
        market_data.get("^TNX", {}).get("price", ""),
        market_data.get("BTC-USD", {}).get("price", ""),
    ]
    file_exists = os.path.exists(csv_file)
    with open(csv_file, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(headers)
        writer.writerow(row)

def save_markdown_report(date_str, time_str, market_data, market_summary, press_reports):
    """서식화된 마크다운 일일 브리핑 리포트 생성"""
    md = []
    md.append(f"# 📊 일일 경제·증시 및 3대 언론사 심층 모닝 브리핑")
    md.append(f"> **기준 시각**: {date_str} {time_str} KST | **공유용 웹 링크**: [{PUBLIC_MASKED_URL}]({PUBLIC_MASKED_URL})\n")
    
    # 1. 마켓 서머리
    md.append("## 💡 시장 핵심 한눈에 보기")
    md.append(f"> {market_summary}\n")

    def format_row(item):
        sym = item["symbol"]
        d = market_data.get(sym, {"price": 0, "diff": 0, "pct": 0})
        p = d["price"]
        pct = d["pct"]
        diff = d["diff"]
        
        if pct > 0:
            sign = "🔺 +"
            badge = f"`+{pct:.2f}%`"
        elif pct < 0:
            sign = "🔻 "
            badge = f"`{pct:.2f}%`"
        else:
            sign = "➖ "
            badge = "`0.00%`"

        return f"| **{item['name']}** | `{p:,.2f} {item['unit']}` | {sign}{abs(diff):,.2f} | {badge} |"

    md.append("### 🌐 미국 및 글로벌 주요 지수")
    md.append("| 지수명 | 마감 지수 | 전일비 | 등락률 |")
    md.append("| :--- | :--- | :--- | :--- |")
    for item in [t for t in TICKERS if t["category"] == "global"]:
        md.append(format_row(item))
    md.append("")

    md.append("### 🇰🇷 국내 증시 (전일 마감)")
    md.append("| 지수명 | 마감 지수 | 전일비 | 등락률 |")
    md.append("| :--- | :--- | :--- | :--- |")
    for item in [t for t in TICKERS if t["category"] == "domestic"]:
        md.append(format_row(item))
    md.append("")

    md.append("### 💵 환율 · 원자재 · 금리 · 가상자산")
    md.append("| 지표명 | 현재가 | 전일비 | 등락률 |")
    md.append("| :--- | :--- | :--- | :--- |")
    for item in [t for t in TICKERS if t["category"] in ["macro", "crypto"]]:
        md.append(format_row(item))
    md.append("\n---\n")

    # 2. 3대 언론사 네이버 뉴스스탠드 1면 전면 기사 및 사설
    md.append("## 📰 [네이버 뉴스스탠드] 경향신문·한국경제·매일경제 1면 전면 기사 & 사설\n")

    for press in press_reports:
        name = press["name"]
        frontpage_arts = press["frontpage"]
        opinions = press["opinions"]

        md.append(f"### 📌 {name}")
        
        # 1면 전면 기사 (첫 화면 맨 앞면 기사)
        md.append(f"#### 🔍 {name} 네이버 뉴스스탠드 첫번째 화면 1면 주요 기사")
        if frontpage_arts:
            for idx, a in enumerate(frontpage_arts, 1):
                top_badge = " **[★ 1면 톱기사]** " if a["is_top"] else " "
                md.append(f"**{idx}.{top_badge}[{a['headline']}]({a['link']})**")
                if a.get("subtitle"):
                    md.append(f"- *소제목/부제목*: {a['subtitle']}")
                md.append(f"- *주요 내용*: {a['summary']}")
                md.append("")
        else:
            md.append("*수집된 1면 기사가 없습니다.*\n")

        # 사설 및 오피니언
        md.append(f"#### ✍️ {name} 오피니언 및 사설 요약")
        if opinions:
            for idx, o in enumerate(opinions, 1):
                md.append(f"**{idx}. [{o['headline']}]({o['link']})**")
                md.append(f"- *핵심 논지 및 요약*: {o['summary']}")
                md.append("")
        else:
            md.append("*수집된 사설/오피니언이 없습니다.*\n")

        md.append("---\n")

    md.append(f"*본 브리핑은 매일 아침 06:00에 자동으로 수집 및 저장됩니다. 공유용 웹 링크: {PUBLIC_MASKED_URL}*")

    full_md = "\n".join(md)

    daily_file = os.path.join(REPORTS_DIR, f"briefing_{date_str.replace('-', '')}.md")
    latest_file = os.path.join(BASE_DIR, "latest_briefing.md")

    with open(daily_file, "w", encoding="utf-8") as f:
        f.write(full_md)
    with open(latest_file, "w", encoding="utf-8") as f:
        f.write(full_md)

    return daily_file, latest_file

def save_html_dashboard(date_str, time_str, market_data, market_summary, press_reports):
    """웹 브라우저에서 보기 쉬운 모던 대시보드 HTML 파일 생성 (공유 기능 탑재)"""
    html_file = os.path.join(BASE_DIR, "index.html")

    def card_html(item):
        sym = item["symbol"]
        d = market_data.get(sym, {"price": 0, "diff": 0, "pct": 0})
        price = d["price"]
        pct = d["pct"]
        diff = d["diff"]

        if pct > 0:
            color = "text-rose-600 bg-rose-50 border-rose-200"
            sign = "+"
            icon = "▲"
        elif pct < 0:
            color = "text-blue-600 bg-blue-50 border-blue-200"
            sign = ""
            icon = "▼"
        else:
            color = "text-gray-600 bg-gray-50 border-gray-200"
            sign = ""
            icon = "-"

        return f"""
        <div class="theme-card bg-white rounded-xl p-4 shadow-sm border border-gray-100 flex flex-col justify-between hover:shadow-md transition">
            <div class="flex justify-between items-center mb-1">
                <span class="text-xs font-semibold theme-subtitle text-gray-400">{sym}</span>
                <span class="text-xs font-bold px-2 py-0.5 rounded-full border {color}">
                    {icon} {sign}{pct:.2f}%
                </span>
            </div>
            <div class="text-sm font-medium theme-title text-gray-700">{item['name']}</div>
            <div class="text-xl font-bold theme-title text-gray-900 mt-1">
                {price:,.2f} <span class="text-xs font-normal theme-subtitle text-gray-500">{item['unit']}</span>
            </div>
            <div class="text-xs theme-subtitle text-gray-400 mt-1">
                전일비 {sign}{diff:,.2f}
            </div>
        </div>
        """

    global_cards = "".join([card_html(t) for t in TICKERS if t["category"] == "global"])
    domestic_cards = "".join([card_html(t) for t in TICKERS if t["category"] == "domestic"])
    macro_cards = "".join([card_html(t) for t in TICKERS if t["category"] in ["macro", "crypto"]])

    articles_map = {}
    for p in press_reports:
        for a in p.get("frontpage", []):
            if "id" in a:
                articles_map[a["id"]] = a
        for o in p.get("opinions", []):
            if "id" in o:
                articles_map[o["id"]] = o
    articles_json_str = json.dumps(articles_map, ensure_ascii=False)

    # 언론사별 뉴스 & 사설 카드
    press_sections_html = ""
    for p in press_reports:
        name = p["name"]
        badge_color = "bg-blue-600" if "경향" in name else ("bg-emerald-600" if "한국" in name else "bg-amber-600")
        
        # 1면 기사 항목
        news_rows = ""
        for idx, n in enumerate(p["frontpage"], 1):
            art_id = n.get("id", f"art_{p['pid']}_{idx}")
            top_tag = '<span class="px-1.5 py-0.5 text-[10px] font-bold bg-rose-600 text-white rounded">1면 톱</span>' if n["is_top"] else f'<span class="text-xs font-bold text-gray-400">{idx}</span>'
            sub_tag = f'<div class="text-xs text-indigo-500 font-medium mt-0.5">{n["subtitle"]}</div>' if n.get("subtitle") else ""
            news_rows += f"""
            <div class="p-3 theme-news-row bg-slate-50 rounded-xl hover:opacity-95 transition space-y-1.5 border border-transparent">
                <div class="flex items-start justify-between gap-2">
                    <div class="flex items-start gap-2">
                        {top_tag}
                        <button type="button" onclick="openArticleModal('{art_id}')" class="text-left text-sm font-bold theme-title hover:text-blue-500 hover:underline">
                            {n['headline']}
                        </button>
                    </div>
                    <a href="{n['link']}" target="_blank" title="신문사 원문 새창 열기" class="text-xs theme-subtitle opacity-60 hover:opacity-100 hover:text-blue-500 flex-shrink-0 pt-0.5">
                        ↗
                    </a>
                </div>
                {sub_tag}
                <p class="text-xs theme-content text-gray-600 leading-relaxed pl-5">{n['summary']}</p>
                <div class="pl-5 pt-0.5 flex items-center justify-between">
                    <button type="button" onclick="openArticleModal('{art_id}')" class="text-[11px] font-semibold text-blue-500 hover:underline flex items-center gap-1 cursor-pointer">
                        <span>📖 세부 신문기사 전문 읽기</span>
                    </button>
                    <span class="text-[10px] theme-subtitle">원문 1면</span>
                </div>
            </div>
            """

        # 사설 항목
        opinion_rows = ""
        for idx, o in enumerate(p["opinions"], 1):
            op_id = o.get("id", f"op_{p['pid']}_{idx}")
            opinion_rows += f"""
            <div class="p-3 theme-opinion-row bg-amber-50/50 rounded-xl border border-amber-100 hover:opacity-95 transition space-y-1.5">
                <div class="flex items-start justify-between gap-2">
                    <div class="flex items-start gap-2">
                        <span class="text-xs font-bold text-amber-600">사설 {idx}</span>
                        <button type="button" onclick="openArticleModal('{op_id}')" class="text-left text-sm font-bold theme-title hover:text-amber-600 hover:underline">
                            {o['headline']}
                        </button>
                    </div>
                    <a href="{o['link']}" target="_blank" title="신문사 원문 새창 열기" class="text-xs theme-subtitle opacity-60 hover:opacity-100 hover:text-amber-500 flex-shrink-0 pt-0.5">
                        ↗
                    </a>
                </div>
                <p class="text-xs theme-opinion-text text-gray-700 leading-relaxed pl-4">{o['summary']}</p>
                <div class="pl-4 pt-0.5 flex items-center justify-between">
                    <button type="button" onclick="openArticleModal('{op_id}')" class="text-[11px] font-semibold text-amber-600 hover:underline flex items-center gap-1 cursor-pointer">
                        <span>📖 사설 전문 읽기</span>
                    </button>
                    <span class="text-[10px] theme-subtitle">오피니언</span>
                </div>
            </div>
            """

        press_sections_html += f"""
        <div class="theme-card bg-white rounded-2xl p-6 shadow-sm border border-gray-100 space-y-4">
            <div class="flex items-center justify-between border-b border-gray-100 pb-3 theme-border-subtle">
                <div class="flex items-center gap-2">
                    <span class="px-2.5 py-1 text-xs font-bold text-white rounded-md {badge_color}">{name}</span>
                    <span class="text-sm font-bold theme-title text-gray-800">네이버 뉴스스탠드 1면 전면 기사 & 사설</span>
                </div>
                <a href="https://newsstand.naver.com/" target="_blank" class="text-xs theme-subtitle text-gray-400 hover:text-blue-500">
                    뉴스스탠드 원문 ↗
                </a>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="space-y-3">
                    <div class="text-xs font-bold theme-subtitle text-gray-500 flex items-center gap-1.5">
                        <span>📰</span> 첫 화면 맨 앞면 기사 (클릭 시 전문 읽기)
                    </div>
                    {news_rows}
                </div>
                <div class="space-y-3">
                    <div class="text-xs font-bold text-amber-600 flex items-center gap-1.5">
                        <span>✍️</span> 오피니언 & 사설 (클릭 시 전문 읽기)
                    </div>
                    {opinion_rows}
                </div>
            </div>
        </div>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="ko" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>경제·증시 & 네이버 뉴스스탠드 3대 언론사 심층 브리핑</title>
    <!-- OpenGraph 메타 태그 (카카오톡, 문자 공유 시 공식 단축링크와 함께 예쁜 카드 제공) -->
    <meta property="og:title" content="📊 일일 경제·증시 & 신문 1면 모닝 브리핑">
    <meta property="og:description" content="{market_summary}">
    <meta property="og:url" content="{PUBLIC_MASKED_URL}">
    <meta property="og:type" content="website">
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/pretendard/1.3.9/static/pretendard.min.css">
    <script>
        (function() {{
            try {{
                var saved = localStorage.getItem('briefing_theme_mode') || 'dark';
                document.documentElement.setAttribute('data-theme', saved);
            }} catch(e) {{}}
        }})();
    </script>
    <style>
        body {{ font-family: 'Pretendard', sans-serif; }}

        /* 테마별 색상 변수 설정 */
        :root, [data-theme="light"] {{
            --bg-page: #f8fafc;
            --bg-card: #ffffff;
            --border-card: #e2e8f0;
            --border-subtle: #f1f5f9;
            --text-primary: #0f172a;
            --text-secondary: #475569;
            --text-muted: #94a3b8;
            --bg-inner-news: #f8fafc;
            --border-inner-news: #e2e8f0;
            --bg-inner-opinion: #fffbeb;
            --border-inner-opinion: #fef3c7;
            --text-inner-opinion: #78350f;
            --bg-switcher: #e2e8f0;
            --border-switcher: #cbd5e1;
            --btn-inactive-text: #64748b;
            --btn-active-bg: #ffffff;
            --btn-active-text: #0f172a;
            --btn-active-shadow: 0 1px 3px rgba(0,0,0,0.12);
            --btn-secondary-bg: #f1f5f9;
            --btn-secondary-text: #334155;
            --btn-secondary-border: #e2e8f0;
            --btn-info-bg: #eff6ff;
            --btn-info-text: #2563eb;
        }}

        [data-theme="gray"] {{
            --bg-page: #c9ced6;             /* 확실한 회색 바탕 */
            --bg-card: #e5e9f0;             /* 부드러운 카드 회색 */
            --border-card: #b0b8c4;
            --border-subtle: #cbd2dc;
            --text-primary: #111827;
            --text-secondary: #374151;
            --text-muted: #6b7280;
            --bg-inner-news: #dbe0e8;
            --border-inner-news: #c2c9d4;
            --bg-inner-opinion: #f3ede2;
            --border-inner-opinion: #dfd4c0;
            --text-inner-opinion: #713f12;
            --bg-switcher: #b4bcc8;
            --border-switcher: #9ba4b2;
            --btn-inactive-text: #374151;
            --btn-active-bg: #ffffff;
            --btn-active-text: #111827;
            --btn-active-shadow: 0 2px 4px rgba(0,0,0,0.15);
            --btn-secondary-bg: #dbe0e8;
            --btn-secondary-text: #1f2937;
            --btn-secondary-border: #b0b8c4;
            --btn-info-bg: #dbeafe;
            --btn-info-text: #1d4ed8;
        }}

        [data-theme="dark"] {{
            --bg-page: #0b0f17;             /* 딥 다크 바탕 */
            --bg-card: #151d2c;             /* 다크 카드 */
            --border-card: #283548;
            --border-subtle: #1f293b;
            --text-primary: #f8fafc;
            --text-secondary: #cbd5e1;
            --text-muted: #8292a6;
            --bg-inner-news: #0d1422;
            --border-inner-news: #283548;
            --bg-inner-opinion: #1f1b16;
            --border-inner-opinion: #3e2f1c;
            --text-inner-opinion: #fde68a;
            --bg-switcher: #1f293b;
            --border-switcher: #334155;
            --btn-inactive-text: #94a3b8;
            --btn-active-bg: #38bdf8;
            --btn-active-text: #0b0f17;
            --btn-active-shadow: 0 2px 6px rgba(56,189,248,0.3);
            --btn-secondary-bg: #1e293b;
            --btn-secondary-text: #e2e8f0;
            --btn-secondary-border: #334155;
            --btn-info-bg: #1e3a5f;
            --btn-info-text: #93c5fd;
        }}

        /* 스타일 매핑 */
        body {{
            background-color: var(--bg-page) !important;
            color: var(--text-secondary);
            transition: background-color 0.25s ease, color 0.25s ease;
        }}
        .theme-card {{
            background-color: var(--bg-card) !important;
            border-color: var(--border-card) !important;
            color: var(--text-secondary);
            transition: background-color 0.25s ease, border-color 0.25s ease;
        }}
        .theme-border-subtle {{
            border-color: var(--border-subtle) !important;
        }}
        .theme-title {{
            color: var(--text-primary) !important;
        }}
        .theme-subtitle {{
            color: var(--text-muted) !important;
        }}
        .theme-content {{
            color: var(--text-secondary) !important;
        }}
        .theme-news-row {{
            background-color: var(--bg-inner-news) !important;
            border-color: var(--border-inner-news) !important;
        }}
        .theme-opinion-row {{
            background-color: var(--bg-inner-opinion) !important;
            border-color: var(--border-inner-opinion) !important;
        }}
        .theme-opinion-text {{
            color: var(--text-inner-opinion) !important;
        }}
        .theme-btn-secondary {{
            background-color: var(--btn-secondary-bg) !important;
            color: var(--btn-secondary-text) !important;
            border-color: var(--btn-secondary-border) !important;
        }}
        .theme-btn-info {{
            background-color: var(--btn-info-bg) !important;
            color: var(--btn-info-text) !important;
        }}
        .theme-switcher-container {{
            background-color: var(--bg-switcher);
            border-color: var(--border-switcher);
        }}
        .theme-pill-btn {{
            color: var(--btn-inactive-text);
            cursor: pointer;
            user-select: none;
        }}
        .theme-pill-btn:hover {{
            opacity: 0.9;
        }}
        .theme-pill-btn.active {{
            background-color: var(--btn-active-bg) !important;
            color: var(--btn-active-text) !important;
            box-shadow: var(--btn-active-shadow);
        }}

        [data-theme="dark"] .bg-rose-50 {{
            background-color: rgba(225, 29, 72, 0.15) !important;
            border-color: rgba(225, 29, 72, 0.4) !important;
            color: #fda4af !important;
        }}
        [data-theme="dark"] .bg-blue-50 {{
            background-color: rgba(37, 99, 235, 0.15) !important;
            border-color: rgba(37, 99, 235, 0.4) !important;
            color: #93c5fd !important;
        }}
        [data-theme="dark"] .bg-gray-50 {{
            background-color: rgba(148, 163, 184, 0.15) !important;
            border-color: rgba(148, 163, 184, 0.3) !important;
            color: #cbd5e1 !important;
        }}
        [data-theme="gray"] .bg-rose-50 {{
            background-color: #fee2e2 !important;
            border-color: #fca5a5 !important;
        }}
        [data-theme="gray"] .bg-blue-50 {{
            background-color: #dbeafe !important;
            border-color: #bfdbfe !important;
        }}

        /* 모달 스크롤바 커스텀 */
        #article-modal ::-webkit-scrollbar {{
            width: 6px;
        }}
        #article-modal ::-webkit-scrollbar-track {{
            background: transparent;
        }}
        #article-modal ::-webkit-scrollbar-thumb {{
            background: var(--border-card);
            border-radius: 9999px;
        }}
    </style>
</head>
<body class="bg-slate-50 text-gray-800 min-h-screen p-3 sm:p-8" data-theme="dark">
    <div class="max-w-5xl mx-auto space-y-5">
        <!-- 맨 상단 우측: 테마 선택 (라이트모드, 그레이모드, 다크모드 둥근 버튼 3개) -->
        <div class="flex items-center justify-between pb-1">
            <div class="flex items-center gap-2 text-xs font-semibold theme-subtitle">
                <span class="inline-block w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
                <span class="font-bold">DAILY BRIEFING</span>
            </div>
            <!-- 맨 상단 우측 둥근 버튼 3개 -->
            <div class="inline-flex p-1 rounded-full theme-switcher-container border shadow-sm items-center gap-1">
                <button type="button" onclick="setTheme('light')" class="theme-pill-btn theme-pill-light rounded-full px-3 py-1.5 text-xs font-bold flex items-center gap-1.5 transition active:scale-95" title="라이트모드">
                    <span>☀️</span><span>라이트<span class="hidden sm:inline">모드</span></span>
                </button>
                <button type="button" onclick="setTheme('gray')" class="theme-pill-btn theme-pill-gray rounded-full px-3 py-1.5 text-xs font-bold flex items-center gap-1.5 transition active:scale-95" title="그레이모드(회색바탕)">
                    <span>🩶</span><span>그레이<span class="hidden sm:inline">모드</span></span>
                </button>
                <button type="button" onclick="setTheme('dark')" class="theme-pill-btn theme-pill-dark rounded-full px-3 py-1.5 text-xs font-bold flex items-center gap-1.5 transition active:scale-95" title="다크모드">
                    <span>🌙</span><span>다크<span class="hidden sm:inline">모드</span></span>
                </button>
            </div>
        </div>

        <!-- Header -->
        <header class="theme-card bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
                <div class="flex items-center gap-2">
                    <span class="text-2xl">📈</span>
                    <h1 class="text-2xl font-bold theme-title text-gray-900">경제·증시 & 언론사 1면 심층 브리핑</h1>
                </div>
                <p class="text-xs theme-subtitle text-gray-500 mt-1">기준 시각: {date_str} {time_str} KST | 출처: 네이버 뉴스스탠드 (경향 · 한경 · 매경 1면)</p>
            </div>
            <!-- 공유 버튼군 -->
            <div class="flex flex-wrap items-center gap-2">
                <button onclick="shareLink()" class="px-3.5 py-2 text-xs font-bold bg-amber-500 text-white rounded-xl hover:bg-amber-600 transition flex items-center gap-1.5 shadow-sm active:scale-95">
                    <span>💬</span> <span>공유하기</span>
                </button>
                <button onclick="copyLink()" class="theme-btn-secondary px-3.5 py-2 text-xs font-semibold bg-gray-100 text-gray-700 rounded-xl hover:bg-gray-200 transition flex items-center gap-1.5 border border-gray-200 active:scale-95">
                    <span>🔗</span> <span>링크 복사</span>
                </button>
            </div>
        </header>

        <!-- Summary Banner -->
        <div class="bg-gradient-to-r from-slate-900 via-indigo-900 to-blue-900 text-white rounded-2xl p-6 shadow-md">
            <div class="text-xs font-bold uppercase tracking-wider text-blue-300 mb-1">Morning Market Insight</div>
            <p class="text-base sm:text-lg font-medium leading-relaxed">{market_summary}</p>
        </div>

        <!-- Global Market -->
        <section>
            <h2 class="text-base font-bold theme-title text-gray-800 mb-3 flex items-center gap-2">
                <span>🌐</span> 미국 및 글로벌 주요 지수
            </h2>
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {global_cards}
            </div>
        </section>

        <!-- Domestic Market -->
        <section>
            <h2 class="text-base font-bold theme-title text-gray-800 mb-3 flex items-center gap-2">
                <span>🇰🇷</span> 국내 증시 (전일 마감)
            </h2>
            <div class="grid grid-cols-2 gap-3">
                {domestic_cards}
            </div>
        </section>

        <!-- Macro & Crypto -->
        <section>
            <h2 class="text-base font-bold theme-title text-gray-800 mb-3 flex items-center gap-2">
                <span>💵</span> 환율 · 원자재 · 금리 · 가상자산
            </h2>
            <div class="grid grid-cols-2 sm:grid-cols-5 gap-3">
                {macro_cards}
            </div>
        </section>

        <!-- Press Section (Kyunghyang, Hankyung, Maekyung from Naver Newsstand) -->
        <section class="space-y-4">
            <h2 class="text-lg font-bold theme-title text-gray-900 flex items-center gap-2 pt-2">
                <span>🗞️</span> 오늘자 네이버 뉴스스탠드 1면 전면 기사 & 사설 분석
            </h2>
            {press_sections_html}
        </section>

        <footer class="text-center text-xs theme-subtitle text-gray-400 py-6 space-y-2">
            <div>aiworks/schedule • 매일 아침 06:00 자동 갱신</div>
            <div>
                공유 링크: <a href="{PUBLIC_MASKED_URL}" target="_blank" class="text-blue-500 hover:underline font-medium">{PUBLIC_MASKED_URL}</a>
            </div>
        </footer>
    </div>

    <!-- 세부 신문기사 전문 모달 (기본 다크모드 & 테마 선택 둥근 버튼 3개 탑재) -->
    <div id="article-modal" class="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/75 backdrop-blur-sm hidden" onclick="handleBackdropClick(event)">
        <div class="theme-card bg-white rounded-2xl shadow-2xl border max-w-3xl w-full max-h-[92vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150" onclick="event.stopPropagation()">
            <!-- 모달 헤더: 언론사 배지, 테마 선택 버튼 3개, 닫기 버튼 -->
            <div class="flex items-center justify-between p-4 sm:p-5 border-b theme-border-subtle flex-wrap gap-2">
                <div class="flex items-center gap-2">
                    <span id="modal-press-badge" class="px-2.5 py-1 text-xs font-bold text-white rounded-md bg-blue-600">신문사</span>
                    <span id="modal-type-badge" class="text-xs font-semibold theme-subtitle">1면 기사</span>
                </div>
                <!-- 모달 상단 우측 둥근 버튼 3개 & 닫기 -->
                <div class="flex items-center gap-2 sm:gap-3">
                    <div class="inline-flex p-1 rounded-full theme-switcher-container border shadow-sm items-center gap-1">
                        <button type="button" onclick="setTheme('light')" class="theme-pill-btn theme-pill-light rounded-full px-2.5 py-1 text-xs font-bold flex items-center gap-1 transition" title="라이트모드">
                            <span>☀️</span><span class="hidden sm:inline">라이트</span>
                        </button>
                        <button type="button" onclick="setTheme('gray')" class="theme-pill-btn theme-pill-gray rounded-full px-2.5 py-1 text-xs font-bold flex items-center gap-1 transition" title="그레이모드(회색바탕)">
                            <span>🩶</span><span class="hidden sm:inline">그레이</span>
                        </button>
                        <button type="button" onclick="setTheme('dark')" class="theme-pill-btn theme-pill-dark rounded-full px-2.5 py-1 text-xs font-bold flex items-center gap-1 transition" title="다크모드">
                            <span>🌙</span><span class="hidden sm:inline">다크</span>
                        </button>
                    </div>
                    <button type="button" onclick="closeArticleModal()" class="w-8 h-8 rounded-full flex items-center justify-center theme-btn-secondary hover:opacity-80 transition text-sm font-bold shadow-sm" title="닫기 (ESC)">
                        ✕
                    </button>
                </div>
            </div>

            <!-- 모달 스크롤 본문 -->
            <div class="p-5 sm:p-8 overflow-y-auto space-y-5">
                <div class="space-y-2">
                    <h2 id="modal-headline" class="text-xl sm:text-2xl font-bold theme-title leading-snug"></h2>
                    <div id="modal-subtitle" class="text-xs sm:text-sm font-semibold text-indigo-400 theme-subtitle border-l-4 border-indigo-500 pl-3 py-1"></div>
                </div>

                <!-- 핵심 요약 박스 -->
                <div id="modal-summary-box" class="p-4 rounded-xl theme-news-row border space-y-1">
                    <div class="text-xs font-bold theme-subtitle flex items-center gap-1">
                        <span>💡</span> 핵심 요약 (Summary)
                    </div>
                    <p id="modal-summary" class="text-xs sm:text-sm theme-content leading-relaxed"></p>
                </div>

                <!-- 기사 전문 단락 -->
                <div class="space-y-3 pt-2">
                    <div class="text-xs font-bold theme-subtitle flex items-center gap-1 border-b pb-2 theme-border-subtle">
                        <span>📰</span> 세부 신문기사 전문 (Full Article)
                    </div>
                    <div id="modal-body-paragraphs" class="space-y-4 text-sm sm:text-base leading-relaxed theme-content"></div>
                </div>
            </div>

            <!-- 모달 푸터 -->
            <div class="p-4 sm:p-5 border-t theme-border-subtle flex items-center justify-between gap-2">
                <a id="modal-orig-link" href="#" target="_blank" class="text-xs font-semibold text-blue-500 hover:underline flex items-center gap-1">
                    <span>신문사 원문 페이지에서 보기</span> <span>↗</span>
                </a>
                <button type="button" onclick="closeArticleModal()" class="px-4 py-2 text-xs font-bold theme-btn-secondary rounded-xl hover:opacity-80 transition">
                    닫기
                </button>
            </div>
        </div>
    </div>

    <!-- 기사 전문 데이터 JSON 및 스크립트 -->
    <script id="articles-data-json" type="application/json">
    {articles_json_str}
    </script>
    <script>
    const MASKED_SHARE_URL = "{PUBLIC_MASKED_URL}";
    let ARTICLES_MAP = {{}};
    try {{
        ARTICLES_MAP = JSON.parse(document.getElementById('articles-data-json').textContent);
    }} catch(e) {{}}

    function setTheme(mode) {{
        if (!['light', 'gray', 'dark'].includes(mode)) mode = 'dark';
        document.documentElement.setAttribute('data-theme', mode);
        document.body.setAttribute('data-theme', mode);
        try {{
            localStorage.setItem('briefing_theme_mode', mode);
        }} catch(e) {{}}

        ['light', 'gray', 'dark'].forEach(function(m) {{
            var btns = document.querySelectorAll('.theme-pill-' + m);
            btns.forEach(function(btn) {{
                if (m === mode) {{
                    btn.classList.add('active');
                }} else {{
                    btn.classList.remove('active');
                }}
            }});
        }});
    }}

    (function() {{
        var saved = 'dark';
        try {{
            saved = localStorage.getItem('briefing_theme_mode') || 'dark';
        }} catch(e) {{}}
        setTheme(saved);
    }})();

    function openArticleModal(artId) {{
        const art = ARTICLES_MAP[artId];
        if (!art) return;

        document.getElementById('modal-headline').textContent = art.headline || '';
        
        const subEl = document.getElementById('modal-subtitle');
        if (art.subtitle) {{
            subEl.textContent = art.subtitle;
            subEl.style.display = 'block';
        }} else {{
            subEl.style.display = 'none';
        }}

        const badgeEl = document.getElementById('modal-press-badge');
        badgeEl.textContent = art.press || '언론사';
        if ((art.press || '').includes('경향')) badgeEl.className = 'px-2.5 py-1 text-xs font-bold text-white rounded-md bg-blue-600';
        else if ((art.press || '').includes('한국')) badgeEl.className = 'px-2.5 py-1 text-xs font-bold text-white rounded-md bg-emerald-600';
        else badgeEl.className = 'px-2.5 py-1 text-xs font-bold text-white rounded-md bg-amber-600';

        document.getElementById('modal-type-badge').textContent = art.type || (art.is_top ? '1면 톱기사' : '1면 주요기사');
        document.getElementById('modal-summary').textContent = art.summary || '';

        const parsContainer = document.getElementById('modal-body-paragraphs');
        parsContainer.innerHTML = '';
        const pars = (art.paragraphs && art.paragraphs.length > 0) ? art.paragraphs : [art.summary || '본문 전문 내용이 없습니다.'];
        pars.forEach(function(p) {{
            const pEl = document.createElement('p');
            pEl.className = 'leading-relaxed text-sm sm:text-base';
            pEl.textContent = p;
            parsContainer.appendChild(pEl);
        }});

        const origLink = document.getElementById('modal-orig-link');
        origLink.href = art.link || '#';

        // 테마 동기화
        var curMode = document.documentElement.getAttribute('data-theme') || 'dark';
        setTheme(curMode);

        document.getElementById('article-modal').classList.remove('hidden');
        document.body.style.overflow = 'hidden';
    }}

    function closeArticleModal() {{
        document.getElementById('article-modal').classList.add('hidden');
        document.body.style.overflow = '';
    }}

    function handleBackdropClick(event) {{
        if (event.target === document.getElementById('article-modal')) {{
            closeArticleModal();
        }}
    }}

    document.addEventListener('keydown', function(e) {{
        if (e.key === 'Escape') {{
            closeArticleModal();
        }}
    }});

    function copyLink() {{
        if (navigator.clipboard && window.isSecureContext) {{
            navigator.clipboard.writeText(MASKED_SHARE_URL).then(() => {{
                alert("📋 공식 브리핑 링크가 복사되었습니다!\\n" + MASKED_SHARE_URL + "\\n\\n카카오톡이나 문자로 지인에게 공유해보세요.");
            }}).catch(() => fallbackPrompt());
        }} else {{
            fallbackPrompt();
        }}
    }}

    function fallbackPrompt() {{
        prompt("아래 공식 공유 링크를 복사하세요:", MASKED_SHARE_URL);
    }}

    function shareLink() {{
        if (navigator.share) {{
            navigator.share({{
                title: "일일 경제·증시 & 신문 1면 브리핑",
                text: "오늘자 경제 지표와 경향·한경·매경 1면 톱기사 모닝 브리핑입니다.\\n👉 " + MASKED_SHARE_URL,
                url: MASKED_SHARE_URL
            }}).catch(() => {{}});
        }} else {{
            copyLink();
        }}
    }}
    </script>
</body>
</html>
"""
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)

def main():
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    
    print(f"[{date_str} {time_str}] 경제·증시 및 네이버 뉴스스탠드 3대 언론사 전면 브리핑 수집 시작...")

    # 1. 지표 수집
    market_data = {}
    for item in TICKERS:
        sym = item["symbol"]
        market_data[sym] = fetch_ticker_data(sym)

    # 2. 시장 요약 생성
    market_summary = generate_market_summary(market_data)

    # 3. 네이버 뉴스스탠드 1면 전면 기사 및 사설 수집 (경향신문 032, 한국경제 015, 매일경제 009)
    print("📰 네이버 뉴스스탠드 1면 전면 기사 및 사설 수집 중...")
    press_configs = [
        {"pid": "032", "name": "경향신문", "opinions_fn": fetch_opinions_kyunghyang},
        {"pid": "015", "name": "한국경제", "opinions_fn": fetch_opinions_hankyung},
        {"pid": "009", "name": "매일경제", "opinions_fn": fetch_opinions_maekyung},
    ]

    press_reports = []
    for cfg in press_configs:
        print(f" - {cfg['name']} (PID: {cfg['pid']}) 뉴스스탠드 1면 및 사설 수집...")
        frontpage_arts = fetch_newsstand_press(cfg["pid"], cfg["name"])
        opinions = cfg["opinions_fn"]()
        press_reports.append({
            "name": cfg["name"],
            "pid": cfg["pid"],
            "frontpage": frontpage_arts,
            "opinions": opinions
        })

    # 4. JSON 원본 저장
    raw_payload = {
        "date": date_str,
        "time": time_str,
        "market_summary": market_summary,
        "market": market_data,
        "press": press_reports
    }
    json_path = os.path.join(DATA_DIR, f"briefing_{date_str.replace('-', '')}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(raw_payload, f, ensure_ascii=False, indent=2)

    # 5. CSV 누적 저장
    save_csv_history(date_str, market_data)

    # 6. 마크다운 리포트 저장
    daily_md, latest_md = save_markdown_report(date_str, time_str, market_data, market_summary, press_reports)

    # 7. HTML 웹 대시보드 저장
    save_html_dashboard(date_str, time_str, market_data, market_summary, press_reports)

    # 8. GitHub Pages (웹 호스팅) 자동 배포
    public_url = sync_to_github_pages(date_str)

    # 9. 스마트폰 팝업 푸시 알림 전송 (ntfy.sh)
    send_mobile_push(date_str, market_summary, click_url=public_url, topic=NTFY_TOPIC)

    print(f"✅ 모든 수집, 웹 배포 및 스마트폰 푸시 알림 완료!")
    print(f" - 로컬 HTML: {os.path.join(BASE_DIR, 'index.html')}")
    print(f" - 공개 단축 링크 (마스킹): {PUBLIC_MASKED_URL}")
    print(f" - 실제 배포 링크: {INTERNAL_HOSTING_URL}")
    print(f" - 스마트폰 푸시 채널: https://ntfy.sh/{NTFY_TOPIC}")

if __name__ == "__main__":
    main()
