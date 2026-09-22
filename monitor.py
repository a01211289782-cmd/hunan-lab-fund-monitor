#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
严格过滤版：监控 水污染控制技术湖南省重点实验室开放基金 申报指南
"""

import requests
from bs4 import BeautifulSoup
import hashlib
import json
import os
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import time
import urllib.parse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==================== 配置 ====================
# 必须同时包含这些核心词才算相关
MUST_CONTAIN = ["开放基金", "申报"]          # 必须包含
STRONG_KEYWORDS = [                         # 强相关词
    "水污染控制技术湖南省重点实验室",
    "水污染控制技术 重点实验室",
    "湖南省重点实验室开放基金",
]

TARGET_SITES = [
    "https://sthjt.hunan.gov.cn/sthjt/xxgk/tzgg/",
    "https://sthjt.hunan.gov.cn/",
]

EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "true").lower() == "true"
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SENDER = os.getenv("SENDER_EMAIL", "")
PASSWORD = os.getenv("EMAIL_PASSWORD", "")
RECEIVER = os.getenv("RECEIVER_EMAIL", "")

HISTORY_FILE = "monitor_history.json"
# ==============================================

def create_session():
    session = requests.Session()
    retry = Retry(total=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.verify = False
    requests.packages.urllib3.disable_warnings()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    return session

session = create_session()

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"seen_hashes": [], "last_check": None}

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def get_content_hash(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()

def is_relevant(title: str) -> bool:
    """严格判断是否相关"""
    title = title.lower()
    # 必须包含“开放基金”和“申报”
    if not all(word in title for word in MUST_CONTAIN):
        return False
    # 必须包含至少一个强相关词
    if not any(kw.lower() in title for kw in STRONG_KEYWORDS):
        return False
    return True

def send_email(subject, content):
    if not EMAIL_ENABLED or not all([SENDER, PASSWORD, RECEIVER]):
        print("邮件未配置，仅打印：")
        print(subject)
        print(content)
        return
    msg = MIMEText(content, "plain", "utf-8")
    msg["From"] = Header(SENDER)
    msg["To"] = Header(RECEIVER)
    msg["Subject"] = Header(subject, "utf-8")
    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SENDER, PASSWORD)
        server.sendmail(SENDER, [RECEIVER], msg.as_string())
        server.quit()
        print("✅ 邮件发送成功")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")

def check_website(url):
    results = []
    try:
        resp = session.get(url, timeout=20)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            if is_relevant(title):
                full_url = urllib.parse.urljoin(url, a["href"])
                results.append({
                    "source": "官网",
                    "title": title[:150],
                    "url": full_url
                })
        print(f"✅ 成功检查: {url}")
    except Exception as e:
        print(f"❌ 检查网站失败: {url} | {str(e)[:80]}")
    return results

def search_baidu(keyword):
    results = []
    try:
        url = f"https://www.baidu.com/s?wd={urllib.parse.quote(keyword)}&rn=10"
        resp = session.get(url, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")
        for item in soup.select(".result, .c-container"):
            title_tag = item.select_one("h3 a") or item.select_one("a")
            if title_tag:
                title = title_tag.get_text(strip=True)
                if is_relevant(title):
                    results.append({
                        "source": "百度",
                        "title": title,
                        "url": title_tag.get("href", "")
                    })
        print(f"✅ 百度搜索完成: {keyword}")
    except Exception as e:
        print(f"❌ 百度失败: {e}")
    return results

def search_bing(keyword):
    results = []
    try:
        url = f"https://cn.bing.com/search?q={urllib.parse.quote(keyword)}&count=10"
        resp = session.get(url, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")
        for item in soup.select("li.b_algo"):
            title_tag = item.select_one("h2 a")
            if title_tag:
                title = title_tag.get_text(strip=True)
                if is_relevant(title):
                    results.append({
                        "source": "必应",
                        "title": title,
                        "url": title_tag.get("href", "")
                    })
        print(f"✅ 必应搜索完成: {keyword}")
    except Exception as e:
        print(f"❌ 必应失败: {e}")
    return results

def run_monitor():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始监控...")
    history = load_history()
    all_results = []

    # 尝试检查官网
    for site in TARGET_SITES:
        all_results.extend(check_website(site))
        time.sleep(1.5)

    # 全网搜索（主要依靠这个）
    search_keywords = [
        "水污染控制技术湖南省重点实验室开放基金 申报指南",
        "水污染控制技术湖南省重点实验室 开放基金",
        "\"水污染控制技术\" 重点实验室 开放基金 申报",
    ]
    for kw in search_keywords:
        all_results.extend(search_baidu(kw))
        time.sleep(2)
        all_results.extend(search_bing(kw))
        time.sleep(2)

    # 去重
    unique_results = []
    for r in all_results:
        content = f"{r.get('title','')}{r.get('url','')}"
        h = get_content_hash(content)
        if h not in history["seen_hashes"]:
            history["seen_hashes"].append(h)
            unique_results.append(r)

    history["seen_hashes"] = history["seen_hashes"][-300:]
    history["last_check"] = datetime.now().isoformat()
    save_history(history)

    if unique_results:
        print(f"🎉 发现 {len(unique_results)} 条高度相关结果！")
        lines = [f"发现时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
        for i, r in enumerate(unique_results, 1):
            lines.append(f"{i}. 【{r['source']}】{r['title']}\n   链接: {r['url']}\n")
        content = "\n".join(lines)
        send_email("【重要】可能发现水污染控制技术湖南省重点实验室开放基金申报指南！", content)
    else:
        print("未发现高度相关新内容。")

    print("监控结束。")

if __name__ == "__main__":
    run_monitor()
