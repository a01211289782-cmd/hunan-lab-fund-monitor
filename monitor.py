#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优化版：每天监控 水污染控制技术湖南省重点实验室开放基金 申报指南
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
import ssl
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==================== 配置 ====================
KEYWORDS = [
    "水污染控制技术湖南省重点实验室开放基金",
    "水污染控制技术湖南省重点实验室 申报指南",
    "水污染控制技术湖南省重点实验室 开放基金 申报",
    "水污染控制技术 重点实验室 开放基金",
]

TARGET_SITES = [
    "https://sthjt.hunan.gov.cn/sthjt/xxgk/tzgg/",  # 通知公告
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

# 创建带重试的 Session
def create_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # 忽略部分 SSL 问题（针对国内政府网站）
    session.verify = False
    requests.packages.urllib3.disable_warnings()
    
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
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

def send_email(subject, content):
    if not EMAIL_ENABLED or not all([SENDER, PASSWORD, RECEIVER]):
        print("邮件未配置或未启用，仅打印结果：")
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
        resp = session.get(url, timeout=25)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text()

        for kw in KEYWORDS:
            if kw in text:
                for a in soup.find_all("a", href=True):
                    link_text = a.get_text(strip=True)
                    if any(k in link_text for k in KEYWORDS) or "开放基金" in link_text or "申报指南" in link_text:
                        full_url = urllib.parse.urljoin(url, a["href"])
                        results.append({
                            "source": "官网",
                            "title": link_text[:150],
                            "url": full_url,
                            "keyword": kw
                        })
                if not results:
                    results.append({
                        "source": "官网",
                        "title": f"页面包含关键词: {kw}",
                        "url": url,
                        "keyword": kw
                    })
        print(f"✅ 成功检查: {url}")
    except Exception as e:
        print(f"❌ 检查网站 {url} 失败: {str(e)[:100]}")
    return results

def search_baidu(keyword, num=10):
    results = []
    try:
        url = f"https://www.baidu.com/s?wd={urllib.parse.quote(keyword)}&rn={num}"
        resp = session.get(url, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")
        for item in soup.select(".result, .c-container"):
            title_tag = item.select_one("h3 a") or item.select_one("a")
            if title_tag:
                title = title_tag.get_text(strip=True)
                href = title_tag.get("href", "")
                if any(k in title for k in KEYWORDS) or "开放基金" in title or "申报指南" in title:
                    results.append({
                        "source": "百度",
                        "title": title,
                        "url": href,
                        "keyword": keyword
                    })
        print(f"✅ 百度搜索完成: {keyword}")
    except Exception as e:
        print(f"❌ 百度搜索失败: {e}")
    return results

def search_bing(keyword, num=10):
    results = []
    try:
        url = f"https://cn.bing.com/search?q={urllib.parse.quote(keyword)}&count={num}"
        resp = session.get(url, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")
        for item in soup.select("li.b_algo"):
            title_tag = item.select_one("h2 a")
            if title_tag:
                title = title_tag.get_text(strip=True)
                href = title_tag.get("href", "")
                if any(k in title for k in KEYWORDS) or "开放基金" in title or "申报指南" in title:
                    results.append({
                        "source": "必应",
                        "title": title,
                        "url": href,
                        "keyword": keyword
                    })
        print(f"✅ 必应搜索完成: {keyword}")
    except Exception as e:
        print(f"❌ 必应搜索失败: {e}")
    return results

def run_monitor():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始监控...")
    history = load_history()
    all_results = []

    # 检查重点网站
    for site in TARGET_SITES:
        all_results.extend(check_website(site))
        time.sleep(2)

    # 全网搜索（更可靠）
    for kw in KEYWORDS:
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

    history["seen_hashes"] = history["seen_hashes"][-500:]
    history["last_check"] = datetime.now().isoformat()
    save_history(history)

    if unique_results:
        print(f"🎉 发现 {len(unique_results)} 条新结果！")
        lines = [f"发现时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
        for i, r in enumerate(unique_results, 1):
            lines.append(f"{i}. 【{r['source']}】{r['title']}\n   链接: {r['url']}\n")
        content = "\n".join(lines)
        send_email("【重要提醒】水污染控制技术湖南省重点实验室开放基金申报指南可能已发布！", content)
    else:
        print("未发现新内容。")

    print("监控结束。")

if __name__ == "__main__":
    run_monitor()
