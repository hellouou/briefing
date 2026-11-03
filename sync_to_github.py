import os
import sys
import shutil
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INS_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "ins"))
INS_ROOT_BRIEFING = os.path.join(INS_DIR, "briefing.html")
INS_DOCS_BRIEFING = os.path.join(INS_DIR, "docs", "briefing.html")

def sync_and_push(commit_msg="Update briefing web dashboard & code"):
    print("[1/3] 로컬 index.html -> ins/briefing.html 및 docs/briefing.html 복사 중...")
    src_html = os.path.join(BASE_DIR, "index.html")
    if not os.path.exists(src_html):
        print("index.html이 없습니다. 먼저 briefing.py를 실행하세요.")
        return False
        
    # 루트 및 docs 동시 복사 (GitHub Pages 루트 배포 완벽 지원)
    shutil.copy2(src_html, INS_ROOT_BRIEFING)
    os.makedirs(os.path.dirname(INS_DOCS_BRIEFING), exist_ok=True)
    shutil.copy2(src_html, INS_DOCS_BRIEFING)
    print("      복사 완료!")

    print("\n[2/3] 깃허브 스테이징 및 커밋 생성 중...")
    subprocess.run(["git", "add", "briefing.html", "docs/briefing.html"], cwd=INS_DIR, check=True)
    
    commit_res = subprocess.run(["git", "commit", "-m", commit_msg], cwd=INS_DIR, capture_output=True, text=True)
    if commit_res.stdout:
        print(commit_res.stdout.strip())
    else:
        print("      최신 변경사항이 반영되었습니다.")

    print("\n[3/3] 깃허브(origin/main)로 푸시하여 실시간 웹 호스팅 갱신 중...")
    push_res = subprocess.run(["git", "push", "origin", "main"], cwd=INS_DIR, capture_output=True, text=True)
    if push_res.returncode == 0:
        print("\n★ [성공] 깃허브 호스팅 완료!")
        print("  - 마스킹 공유 링크: https://tr.ee/Z51VtU")
        print("  - 실제 호스팅 링크: https://hellouou.github.io/ins/briefing.html")
        return True
    else:
        print(f"\n[오류] 푸시 실패: {push_res.stderr}")
        return False

if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "Auto Sync: Update morning briefing masked link & dashboard"
    sync_and_push(msg)

