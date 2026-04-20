import os
import json
import requests
import re
import time
import sys
import subprocess

# --- 라이브러리 자동 설치 로직 ---
def install_dependencies():
    required = ["requests", "beautifulsoup4", "yt-dlp", "static-ffmpeg", "playwright"]
    missing = []
    
    for lib in required:
        pkg_name = "beautifulsoup4" if lib == "beautifulsoup4" else lib
        try:
            __import__(lib.replace("-", "_"))
        except ImportError:
            missing.append(lib)
    
    if missing:
        print(f"누락된 라이브러리 설치 중: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
        
        if "playwright" in missing:
            print("브라우저(Chromium) 설치 중...")
            subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        
        print("설치 완료! 프로그램을 다시 시작합니다.\n")
        os.execv(sys.executable, ['python'] + sys.argv)

if __name__ == "__main__":
    # 메인 로직 실행 전 설치 확인
    if not os.environ.get("SKIP_DEP_CHECK"):
        os.environ["SKIP_DEP_CHECK"] = "1"
        install_dependencies()

# --- 기존 로직 시작 ---
from bs4 import BeautifulSoup
import yt_dlp
from static_ffmpeg import add_paths
from playwright.sync_api import sync_playwright

# ffmpeg 경로 설정
add_paths()

class HansungDownloader:
    def __init__(self, config_path='config.json'):
        self.config_path = config_path
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        self.base_url = "https://learn.hansung.ac.kr"
        self.login_url = f"{self.base_url}/login.php"
        self.config = self.load_config()

    def load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            config = {"download_path": "./downloads"}
            self.save_config(config)
            return config

    def save_config(self, config):
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

    def login(self):
        if 'moodle_session' in self.config:
            self.session.cookies.set('MoodleSession', self.config['moodle_session'], domain='learn.hansung.ac.kr')
            if self.check_login_success(silent=True):
                print("저장된 세션으로 로그인되었습니다.")
                return True

        print("\n브라우저를 통해 자동 로그인을 시도합니다...")
        username = self.config.get('username')
        password = self.config.get('password')
        
        if not username or not password:
            username = input("학번: ").strip()
            password = input("비밀번호: ").strip()
            self.config['username'] = username
            self.config['password'] = password
            self.save_config(self.config)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(user_agent=self.session.headers['User-Agent'])
                page = context.new_page()
                page.goto(self.login_url)
                page.wait_for_selector("#input-username")
                page.fill("#input-username", username)
                page.fill("#input-password", password)
                page.click("input[type='submit']")
                try:
                    page.wait_for_url(lambda url: "login.php" not in url, timeout=10000)
                except: pass
                cookies = context.cookies()
                moodle_session = next((c['value'] for c in cookies if c['name'] == 'MoodleSession'), None)
                browser.close()
                if moodle_session:
                    self.config['moodle_session'] = moodle_session
                    self.save_config(self.config)
                    self.session.cookies.set('MoodleSession', moodle_session, domain='learn.hansung.ac.kr')
                    if self.check_login_success(): return True
        except Exception as e:
            print(f"브라우저 로그인 중 오류 발생: {e}")

        print("\n자동 로그인이 실패했습니다. 수동으로 쿠키를 입력해주세요.")
        moodle_session = input("MoodleSession: ").strip()
        if moodle_session:
            self.config['moodle_session'] = moodle_session
            self.save_config(self.config)
            self.session.cookies.set('MoodleSession', moodle_session, domain='learn.hansung.ac.kr')
            return self.check_login_success()
        return False

    def check_login_success(self, silent=False):
        try:
            response = self.session.get(self.base_url, timeout=5)
            if 'logout.php' in response.text:
                if not silent:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    user_name = soup.select_one(".user_name, .userinfo, .my-name, .fullname")
                    print(f"로그인 성공! ({user_name.get_text().strip() if user_name else '사용자'}님)")
                return True
        except: pass
        return False

    def get_course_list(self):
        response = self.session.get(self.base_url)
        soup = BeautifulSoup(response.text, 'html.parser')
        courses = []
        course_elements = soup.select(".course_box, .course_link, .course_lists .course_link, .fullname")
        if not course_elements:
            course_elements = [a for a in soup.find_all('a', href=True) if '/course/view.php?id=' in a['href']]
        for element in course_elements:
            link_tag = element if element.name == 'a' else element.find('a')
            if not link_tag or '/course/view.php?id=' not in link_tag.get('href', ''): continue
            link = link_tag['href']
            title = element.get_text().strip()
            if not title: title = link_tag.get_text().strip()
            if not title or title == "강의실": continue
            if not any(c['url'] == link for c in courses):
                courses.append({"id": len(courses), "title": title, "url": link})
        return courses

    def get_video_list(self, course_url):
        response = self.session.get(course_url)
        soup = BeautifulSoup(response.text, 'html.parser')
        videos = []
        vod_elements = soup.select("li.modtype_vod")
        for element in vod_elements:
            week_section = element.find_parent("li", class_="section")
            week_name = "Unknown"
            if week_section:
                week_attr = week_section.get("aria-label", "")
                if week_attr: week_name = week_attr.split('[')[0].strip()
            link_tag = element.find("a")
            if not link_tag: continue
            viewer_url = ""
            onclick = link_tag.get('onclick', '')
            if 'viewer.php' in onclick:
                match = re.search(r"'(https?://[^']+viewer\.php\?id=\d+)'", onclick)
                if match: viewer_url = match.group(1)
            if not viewer_url:
                href = link_tag.get('href', '')
                if 'viewer.php' in href or 'view.php' in href:
                    viewer_url = href if 'viewer.php' in href else href.replace('view.php', 'viewer.php')
            if viewer_url:
                title = link_tag.select_one(".instancename").get_text().replace(" 동영상", "").strip() if link_tag.select_one(".instancename") else "영상"
                videos.append({"week": week_name, "url": viewer_url, "title": title})
        return videos

    def extract_m3u8(self, viewer_url):
        response = self.session.get(viewer_url)
        soup = BeautifulSoup(response.text, 'html.parser')
        source_tag = soup.find("source")
        if source_tag and source_tag.get('src'): return source_tag['src']
        match = re.search(r"file\s*:\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]", response.text)
        if match: return match.group(1)
        match = re.search(r"src\s*:\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]", response.text)
        if match: return match.group(1)
        return None

    def download_video(self, m3u8_url, output_path):
        ydl_opts = {'format': 'best', 'outtmpl': output_path, 'quiet': True, 'no_warnings': True, 'nocheckcertificate': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for cookie in self.session.cookies: ydl.cookiejar.set_cookie(cookie)
            ydl.download([m3u8_url])

    def run(self):
        if not self.login(): return
        while True:
            courses = self.get_course_list()
            if not courses: print("과목 목록 로드 실패."); break
            print("\n" + "="*30 + "\n [한성대 영상 다운로더] \n" + "="*30)
            for c in courses: print(f"{c['id']}. {c['title']}")
            print("q. 종료")
            c_choice = input("\n과목 번호 입력: ").strip().lower()
            if c_choice == 'q': break
            try:
                course = courses[int(c_choice)]
                videos = self.get_video_list(course['url'])
                print(f"\n[{course['title']}] {len(videos)}개의 영상을 찾았습니다.")
                if not videos: continue
                for i, v in enumerate(videos, 1): print(f"  {i}. [{v['week']}] {v['title']}")
                print("\n선택: 숫자(예: 1,2,5), 'all'(전체), 'b'(뒤로)")
                v_choice = input("입력: ").strip().lower()
                if v_choice == 'b': continue
                selected_indices = list(range(len(videos))) if v_choice == 'all' else [int(x.strip()) - 1 for x in v_choice.split(',')]
                for idx in selected_indices:
                    if 0 <= idx < len(videos):
                        v = videos[idx]
                        m3u8_url = self.extract_m3u8(v['url'])
                        if m3u8_url:
                            filename = f"{re.sub(r'[\\/:*?\"<>|]', '_', course['title'])}_{re.sub(r'[\\/:*?\"<>|]', '_', v['week'])}_{idx+1:02d}_{re.sub(r'[\\/:*?\"<>|]', '_', v['title'])}.mp4"
                            save_dir = os.path.join(self.config['download_path'], re.sub(r'[\\/:*?\"<>|]', '_', course['title']))
                            if not os.path.exists(save_dir): os.makedirs(save_dir)
                            path = os.path.join(save_dir, filename)
                            if os.path.exists(path): print(f"[건너뛰기] {filename}"); continue
                            print(f"Downloading: {filename}..."); self.download_video(m3u8_url, path); print(f"Done: {filename}")
                        else: print(f"m3u8 추출 실패: {v['title']}")
            except Exception as e: print(f"에러 발생: {e}")
        print("프로그램을 종료합니다.")

if __name__ == "__main__":
    # install_dependencies() 가 호출된 후 실제 앱 실행
    # (이미 위 if __name__ == "__main__" 블록에서 처리됨)
    HansungDownloader().run()
