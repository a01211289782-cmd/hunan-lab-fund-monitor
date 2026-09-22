#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
水污染控制技术湖南省重点实验室开放基金监控脚本

数据源：
  1. 湖南省生态环境厅通知公告 API（api.hunan.gov.cn）
  2. 湖南省科学技术厅通知公告（静态 HTML 解析）
  3. 湖南省环境保护科学研究院官网（可选，best-effort）

匹配策略（精确匹配）：
  - 开放词：开放基金 / 开放课题 / 开放研究基金 / 开放项目
  - 实验室词：水污染控制技术湖南省重点实验室 / 水污染控制+重点实验室
  - 行为词：申报 / 申请 / 指南 / 通知 / 项目 / 征集
  - 匹配规则：(开放词 AND 实验室词) OR (实验室词 AND 行为词)
  - 科技厅结果支持抓取正文做二次验证
"""

import requests
import json
import os
import hashlib
import time
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.header import Header
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== 配置 ====================

# 核心词（开放基金类）
OPEN_KEYWORDS = ["开放基金", "开放课题", "开放研究基金", "开放项目"]

# 实验室精确匹配词
EXACT_LAB_KEYWORDS = [
    "水污染控制技术湖南省重点实验室",
    "水污染控制技术 重点实验室",
]

# 行为词（申报/申请/指南等）
ACTION_KEYWORDS = ["申报", "申请", "指南", "通知", "项目", "征集"]

# 通知公告栏目 channelId（从页面 JS 中提取）
STHJT_CHANNELS = [
    {"id": "97433", "name": "生态环境厅-通知", "base_url": "http://sthjt.hunan.gov.cn"},
    {"id": "97434", "name": "生态环境厅-公告", "base_url": "http://sthjt.hunan.gov.cn"},
]

# 湖南省科技厅通知公告（静态 HTML 可直接解析）
KJT_PAGES = [
    {"url": "http://kjt.hunan.gov.cn/kjt/xxgk/tzgg/tzgg_1/", "name": "科技厅-通知公告"},
]

# HRAES 官网（best-effort，可能连不上）
HRAES_URLS = [
    "http://www.hraes.cn/",
]

# 邮件配置
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "true").lower() not in ("false", "0", "no")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SENDER = os.getenv("SENDER_EMAIL", "")
PASSWORD = os.getenv("EMAIL_PASSWORD", "")
RECEIVER = os.getenv("RECEIVER_EMAIL", "")

# 历史记录文件
HISTORY_FILE = "monitor_history.json"
HISTORY_MAX = 500  # 最多保存 500 条历史记录

# 每次抓取的页数
API_PAGES = 3      # API 每页 20 条，抓 3 页 = 60 条/栏目
KJT_PAGES_TO_FETCH = 2  # 科技厅通知页数


# ==================== HTTP 会话 ====================

def create_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    return session


session = create_session()


# ==================== 历史记录 ====================

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            # 兼容旧版历史文件格式（旧脚本用的是 "seen_hashes" 字段）
            if "seen_keys" not in history:
                history["seen_keys"] = history.get("seen_hashes", [])
            return history
        except (json.JSONDecodeError, IOError):
            pass
    return {"seen_keys": [], "last_check": None}


def save_history(history):
    history.setdefault("seen_keys", [])
    history["seen_keys"] = history["seen_keys"][-HISTORY_MAX:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def make_dedup_key(source, identifier):
    """生成去重 key：source + manuscriptId 或 url"""
    return hashlib.md5(f"{source}|{identifier}".encode("utf-8")).hexdigest()


# ==================== 关键词匹配 ====================

def is_relevant(title, content=""):
    """
    精确匹配逻辑：
    - 包含开放词 AND (精确实验室名 OR 水污染控制+重点实验室) → 通过
    - 或 (精确实验室名 OR 水污染控制+重点实验室) AND 行为词 → 通过
    - content 为 API 返回的文章摘要，用于辅助判断
    """
    text = f"{title} {content}".replace(" ", "").lower()

    has_open = any(k.replace(" ", "").lower() in text for k in OPEN_KEYWORDS)
    has_exact_lab = any(k.replace(" ", "").lower() in text for k in EXACT_LAB_KEYWORDS)
    has_water_lab = ("水污染控制" in text and "重点实验室" in text)
    has_action = any(k.lower() in text for k in ACTION_KEYWORDS)

    # 开放基金 + 实验室相关
    if has_open and (has_exact_lab or has_water_lab):
        return True

    # 实验室相关 + 行为词
    if (has_exact_lab or has_water_lab) and has_action:
        return True

    return False


def relevance_score(title, content=""):
    """计算相关度评分，用于排序"""
    text = f"{title} {content}".replace(" ", "").lower()
    score = 0
    for kw in OPEN_KEYWORDS:
        if kw.replace(" ", "").lower() in text:
            score += 10
    for kw in EXACT_LAB_KEYWORDS:
        if kw.replace(" ", "").lower() in text:
            score += 5
    if "水污染控制" in text and "重点实验室" in text:
        score += 5
    for kw in ACTION_KEYWORDS:
        if kw.lower() in text:
            score += 2
    return score


# ==================== 数据源：湖南省生态环境厅 API ====================

def fetch_sthjt_api(channel):
    """通过湖南省政府统一 API 获取生态环境厅通知公告"""
    results = []
    channel_id = channel["id"]
    base_url = channel["base_url"]
    api_url = f"http://api.hunan.gov.cn/search/common/search/{channel_id}"

    for page in range(1, API_PAGES + 1):
        payload = {
            "datas": [
                {"key": "status", "value": "4", "join": "and", "queryType": "term"},
                {"key": "publishedTime", "sort": "true", "order": "desc", "queryType": "term"},
            ],
            "page": page,
            "_pageSize": 20,
            "_isAgg": "true",
        }
        try:
            resp = session.post(
                api_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=20,
                verify=False,
            )
            if resp.status_code != 200:
                print(f"  [{channel['name']}] 第{page}页 HTTP {resp.status_code}")
                break

            data = resp.json()
            items = data.get("data", {}).get("results", [])
            if not items:
                break

            for item in items:
                title = item.get("title", "")
                url = item.get("url", "")
                content = item.get("content", "")
                published = item.get("publishedTimeStr", "")
                manuscript_id = item.get("manuscriptId", "")

                if not title:
                    continue

                # 客户端关键词过滤
                if is_relevant(title, content):
                    full_url = f"{base_url}{url}" if url else ""
                    dedup_key = make_dedup_key("sthjt", manuscript_id or url)
                    results.append({
                        "source": channel["name"],
                        "title": title[:200],
                        "url": full_url,
                        "date": published[:10] if published else "",
                        "content_preview": content[:300] if content else "",
                        "score": relevance_score(title, content),
                        "dedup_key": dedup_key,
                    })

            print(f"  [{channel['name']}] 第{page}页: {len(items)} 条，筛选后 {sum(1 for r in results if r['source'] == channel['name'])} 条")
            time.sleep(0.5)
        except Exception as e:
            print(f"  [{channel['name']}] 第{page}页失败: {str(e)[:80]}")
            break

    return results


# ==================== 数据源：湖南省科技厅 ====================

def fetch_article_text(url):
    """抓取文章页面正文文本（用于科技厅通知的二次验证）"""
    try:
        resp = session.get(url, timeout=15, verify=False)
        resp.encoding = resp.apparent_encoding or "utf-8"
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "lxml")
        # 尝试常见正文容器
        for selector in [".article-content", ".content", "#zoom", ".TRS_Editor", ".page_content", ".main-content", "article", ".news_content"]:
            node = soup.select_one(selector)
            if node:
                return node.get_text(strip=True)[:2000]
        # 退而求其次：取 body 全文
        body = soup.find("body")
        return body.get_text(strip=True)[:2000] if body else ""
    except Exception:
        return ""


def fetch_kjt_page(page_config):
    """解析湖南省科技厅通知公告页面（静态 HTML）"""
    results = []
    url = page_config["url"]
    try:
        resp = session.get(url, timeout=20, verify=False)
        resp.encoding = resp.apparent_encoding or "utf-8"
        if resp.status_code != 200:
            print(f"  [{page_config['name']}] HTTP {resp.status_code}")
            return results

        soup = BeautifulSoup(resp.text, "lxml")
        links = soup.find_all("a", href=True)

        import re
        for a in links:
            href = a["href"]
            title = a.get_text(strip=True)

            # 只看带日期的通知链接（如 /202609/t20260910_12345.html）
            if not re.search(r"/\d{6}/t\d{8}_\d+", href):
                continue
            if not title or len(title) < 5:
                continue
            # 排除导航类链接
            if any(kw in href for kw in ["jgzn", "jgld", "nsjg", "zsjg", "pzjg"]):
                continue

            # 先用标题粗筛
            if not is_relevant(title):
                # 标题不够但可能正文提到实验室，做二次检查
                if any(kw in title for kw in ["开放", "重点实验室", "水污染"]):
                    full_url = f"http://kjt.hunan.gov.cn{href}" if href.startswith("/") else href
                    body_text = fetch_article_text(full_url)
                    if is_relevant(title, body_text):
                        dedup_key = make_dedup_key("kjt", href)
                        results.append({
                            "source": page_config["name"],
                            "title": title[:200],
                            "url": full_url,
                            "date": "",
                            "content_preview": body_text[:300],
                            "score": relevance_score(title, body_text),
                            "dedup_key": dedup_key,
                        })
                continue

            full_url = f"http://kjt.hunan.gov.cn{href}" if href.startswith("/") else href
            dedup_key = make_dedup_key("kjt", href)
            results.append({
                "source": page_config["name"],
                "title": title[:200],
                "url": full_url,
                "date": "",
                "content_preview": "",
                "score": relevance_score(title),
                "dedup_key": dedup_key,
            })

        print(f"  [{page_config['name']}] 筛选后 {len(results)} 条")
    except Exception as e:
        print(f"  [{page_config['name']}] 失败: {str(e)[:80]}")

    return results


# ==================== 数据源：HRAES（best-effort） ====================

def fetch_hraes():
    """尝试获取湖南省环境保护科学研究院官网（可能连不上）"""
    results = []
    for url in HRAES_URLS:
        try:
            resp = session.get(url, timeout=8, verify=False)
            if resp.status_code != 200:
                continue
            resp.encoding = resp.apparent_encoding or "utf-8"
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.find_all("a", href=True):
                title = a.get_text(strip=True)
                if title and is_relevant(title):
                    from urllib.parse import urljoin
                    full_url = urljoin(url, a["href"])
                    dedup_key = make_dedup_key("hraes", full_url)
                    results.append({
                        "source": "环科院官网",
                        "title": title[:200],
                        "url": full_url,
                        "date": "",
                        "content_preview": "",
                        "score": relevance_score(title),
                        "dedup_key": dedup_key,
                    })
            print(f"  [环科院官网] 筛选后 {len(results)} 条")
        except Exception as e:
            print(f"  [环科院官网] 不可达（正常现象）: {str(e)[:60]}")
    return results


# ==================== 邮件通知 ====================

def send_email(subject, content):
    if not EMAIL_ENABLED:
        print("邮件未启用，仅打印：")
        print(f"  主题: {subject}")
        print(f"  内容:\n{content}")
        return
    if not all([SENDER, PASSWORD, RECEIVER]):
        print("邮件配置不完整，仅打印：")
        print(f"  主题: {subject}")
        print(f"  内容:\n{content}")
        return

    msg = MIMEText(content, "plain", "utf-8")
    msg["From"] = Header(SENDER)
    msg["To"] = Header(RECEIVER)
    msg["Subject"] = Header(subject, "utf-8")
    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30)
        server.login(SENDER, PASSWORD)
        server.sendmail(SENDER, [RECEIVER], msg.as_string())
        server.quit()
        print("✅ 邮件发送成功")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")


# ==================== 主流程 ====================

def run_monitor():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始监控...")
    history = load_history()
    all_results = []

    # 1. 生态环境厅 API
    print("正在检查生态环境厅...")
    for channel in STHJT_CHANNELS:
        all_results.extend(fetch_sthjt_api(channel))
        time.sleep(1)

    # 2. 科技厅通知公告
    print("正在检查科技厅...")
    for page_config in KJT_PAGES:
        all_results.extend(fetch_kjt_page(page_config))
        time.sleep(1)

    # 3. 环科院官网（best-effort，失败不影响整体）
    print("正在检查环科院官网（best-effort）...")
    all_results.extend(fetch_hraes())

    # 去重（基于 dedup_key，对照历史记录）
    seen_keys = set(history.get("seen_keys", []))
    new_results = []
    for r in all_results:
        key = r["dedup_key"]
        if key not in seen_keys:
            seen_keys.add(key)
            history["seen_keys"].append(key)
            new_results.append(r)

    # 按相关度评分排序，分数高的在前
    new_results.sort(key=lambda r: r["score"], reverse=True)

    history["last_check"] = datetime.now().isoformat()
    save_history(history)

    if new_results:
        print(f"🎉 发现 {len(new_results)} 条新的相关结果！")
        lines = [f"发现时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
        for i, r in enumerate(new_results, 1):
            lines.append(
                f"{i}. 【{r['source']}】(评分:{r['score']}) {r['title']}\n"
                f"   日期: {r['date'] or '未知'}\n"
                f"   链接: {r['url']}\n"
                + (f"   摘要: {r['content_preview']}\n" if r['content_preview'] else "")
            )
        content = "\n".join(lines)
        send_email(
            "【重要】水污染控制技术湖南省重点实验室开放基金相关通知更新",
            content,
        )
    else:
        print("未发现新的相关内容。")

    print("监控结束。")


if __name__ == "__main__":
    run_monitor()
