# -*- coding: utf-8 -*-
"""本地 API 凭据存储（两级配置文件）。

读取优先级（高 → 低）：
1. 系统环境变量
2. deploy/show-v2/api-config.json   —— 项目内，展示机 / 本地部署用
3. ~/.finsight/config.json          —— 用户级，跨项目的个人配置

约束：
1. 两个配置文件都被 .gitignore 忽略，且被打包白名单双重拦截，不会上传。
2. 文件权限 0600、目录 0700（POSIX 下生效，Windows 忽略）。
3. 只在服务启动时读入环境变量；页面不提供写入接口，公网无法通过网页改密钥。
4. 对外只暴露掩码与"是否已配置"，永不返回完整密钥。
"""

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 项目内配置：跟着项目文件夹走，拷到展示机就能直接用
PROJECT_FILE = HERE / "api-config.json"
PROJECT_EXAMPLE = HERE / "api-config.example.json"

# 用户级配置：跨项目复用，不在项目目录里
CONFIG_DIR = Path(os.path.expanduser("~")) / ".finsight"
CONFIG_FILE = CONFIG_DIR / "config.json"

# 由 load_into_env() 从文件补进环境变量的项，用于准确标注来源
_FROM_FILE = set()
# key -> "project" / "user"，记录是哪一层文件提供的
_SOURCES = {}

# key -> 配置元数据
# secret=True 的项对外只给掩码；False 的项明文展示（地址、模型名不是密钥）
# optional=True 的项留空就跳过，不写进配置也不影响启动
FIELDS = {
    "ifind": {
        "env": "IFIND_MCP_AUTHORIZATION",
        "label": "iFinD 授权串",
        "secret": True,
        "hint": "新闻检索、行情、标的共用同一个授权串",
    },
    "deepseek": {
        "env": "DEEPSEEK_API_KEY",
        "label": "DeepSeek API Key",
        "secret": True,
        "hint": "新闻摘要、质量审核与智能分析",
    },
    "tavily": {
        "env": "TAVILY_API_KEY",
        "label": "Tavily API Key",
        "secret": True,
        "optional": True,
        "hint": "可选：分析时补充公开网页证据，留空则跳过",
    },
    "deepseek_base_url": {
        "env": "DEEPSEEK_BASE_URL",
        "label": "DeepSeek 接口地址",
        "secret": False,
        "optional": True,
        "hint": "可选：用中转或自建服务时填写，留空用官方地址",
    },
    "deepseek_model": {
        "env": "DEEPSEEK_MODEL",
        "label": "DeepSeek 模型名",
        "secret": False,
        "optional": True,
        "hint": "可选：留空用项目默认模型",
    },
}

# 需要用户填写的密钥项（setup_keys.py 只问这些）
SECRET_FIELDS = [key for key, meta in FIELDS.items() if meta["secret"]]


def _read_file(path):
    """读一个配置文件，只保留认识的键。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key, meta in FIELDS.items():
        value = str(data.get(key) or "").strip()
        if value:
            out[key] = value
    return out


def read_project():
    return _read_file(PROJECT_FILE)


def read_user():
    """只读用户级配置（setup_keys.py 写入前取原值用）。"""
    return _read_file(CONFIG_FILE)


def read():
    """合并后的配置：用户级为底，项目内覆盖。"""
    merged = _read_file(CONFIG_FILE)
    merged.update(_read_file(PROJECT_FILE))
    return merged


def write(values):
    """写入用户级配置；空值表示删除该项。"""
    payload = {}
    for key, value in (values or {}).items():
        if key in FIELDS:
            text = str(value or "").strip()
            if text:
                payload[key] = text
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass
    temporary = CONFIG_FILE.with_name(".config.json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, CONFIG_FILE)
    return payload


def clear():
    try:
        CONFIG_FILE.unlink()
        return True
    except OSError:
        return False


def load_into_env():
    """把文件里的凭据补进环境变量；已存在的环境变量优先，不被覆盖。"""
    global _FROM_FILE, _SOURCES
    user = _read_file(CONFIG_FILE)
    project = _read_file(PROJECT_FILE)
    merged = dict(user)
    merged.update(project)
    origin = {key: "user" for key in user}
    origin.update({key: "project" for key in project})

    applied = []
    sources = {}
    for key, meta in FIELDS.items():
        env = meta["env"]
        if (os.environ.get(env) or "").strip():
            continue
        value = str(merged.get(key) or "").strip()
        if value:
            os.environ[env] = value
            applied.append(key)
            sources[key] = origin.get(key, "")
    _FROM_FILE = set(applied)
    _SOURCES = sources
    return applied


def masked(value):
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return text[:4] + "****" + text[-4:]


def status():
    """返回各配置项的状态（含掩码与来源），不含完整密钥。"""
    user = _read_file(CONFIG_FILE)
    project = _read_file(PROJECT_FILE)
    out = {}
    for key, meta in FIELDS.items():
        env = meta["env"]
        from_env = (os.environ.get(env) or "").strip()
        value = from_env or project.get(key) or user.get(key) or ""
        # load_into_env() 会把文件里的值写进环境变量，此时不能据此判断成"环境变量"
        if key in _FROM_FILE and _SOURCES.get(key):
            source = _SOURCES[key]
        elif from_env:
            source = "env"
        elif project.get(key):
            source = "project"
        elif user.get(key):
            source = "user"
        else:
            source = ""
        out[key] = {
            "label": meta["label"],
            "env": env,
            "hint": meta["hint"],
            "secret": bool(meta["secret"]),
            "optional": bool(meta.get("optional")),
            "configured": bool(value),
            "masked": masked(value) if meta["secret"] else value,
            "source": source,
        }
    return out


def paths():
    """两个配置文件的位置与是否存在，供页面与脚本提示用。"""
    return {
        "project": str(PROJECT_FILE),
        "projectExists": PROJECT_FILE.is_file(),
        "example": str(PROJECT_EXAMPLE),
        "exampleExists": PROJECT_EXAMPLE.is_file(),
        "user": str(CONFIG_FILE),
        "userExists": CONFIG_FILE.is_file(),
    }


def config_path():
    """兼容旧调用：返回用户级配置文件路径。"""
    return str(CONFIG_FILE)
