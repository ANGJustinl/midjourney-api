import json
import os
import asyncio
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Union, Optional


import aiohttp
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables and clean them
load_dotenv()

def clean_env_value(value: str) -> str:
    """Clean environment variable value by removing quotes and comments"""
    if not value:
        return value
    # Remove comments
    value = value.split('#')[0].strip()
    # Remove quotes
    value = value.strip('"\'')
    return value

# Constants
DRAW_VERSION = int(os.getenv("DRAW_VERSION"))  # Discord interaction version

# Configuration validation and cleaning
def validate_config():
    """Validate required environment variables"""
    missing = []
    required_vars = ["DISCORD_CHANNEL_ID", "DISCORD_GUILD_ID"]
    token_vars = ["DISCORD_USER_TOKEN", "DISCORD_BOT_TOKEN"]
    
    # Check required variables
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)
    
    # Check if at least one token is present
    if not any(os.getenv(var) for var in token_vars):
        missing.append("DISCORD_USER_TOKEN or DISCORD_BOT_TOKEN")
    
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Please check .env.example for configuration instructions.\n"
            "Note: Either USER_TOKEN or BOT_TOKEN must be provided."
        )

# Validate configuration
validate_config()

# Configuration with cleaned values
CHANNEL_ID = clean_env_value(os.getenv("DISCORD_CHANNEL_ID"))
USER_TOKEN = clean_env_value(os.getenv("DISCORD_USER_TOKEN"))
BOT_TOKEN = clean_env_value(os.getenv("DISCORD_BOT_TOKEN"))
GUILD_ID = clean_env_value(os.getenv("DISCORD_GUILD_ID"))
DRAW_VERSION = clean_env_value(os.getenv("DRAW_VERSION", "1237876415471554623"))
PROXY_URL = clean_env_value(os.getenv("PROXY_URL"))
CALLBACK_URL = clean_env_value(os.getenv("CALLBACK_URL"))

# Log configuration status
from loguru import logger
logger.info("Discord configuration loaded")
logger.debug(f"Channel ID: {CHANNEL_ID}")
logger.debug(f"Guild ID: {GUILD_ID}")
logger.debug(f"MJ Version: {DRAW_VERSION}")
logger.debug(f"Proxy URL: {PROXY_URL or 'Not configured'}")
logger.debug(f"Callback URL: {CALLBACK_URL or 'Not configured'}")

# 创建全局回调存储
task_callbacks: Dict[str, Dict[str, Any]] = {}
# 添加一个映射来关联不同的ID
trigger_id_mapping: Dict[str, str] = {}

def register_mapping(origin_id: str, related_id: str) -> None:
    """注册ID映射，建立不同ID系统之间的关联
    origin_id: 原始的、带连字符的UUID trigger_id
    related_id: 任何需要关联到origin_id的ID (e.g., message_id, hash, nonce_without_hyphens)
    """
    global trigger_id_mapping
    
    # Ensure origin_id is the canonical, hyphenated UUID form if it looks like a UUID
    if len(origin_id) == 32 and '-' not in origin_id:
        # This should not happen if called correctly, but as a safeguard
        logger.warning(f"register_mapping called with a non-hyphenated UUID as origin_id: {origin_id}. This might be an issue.")
        # Attempt to re-hyphenate or find the canonical form if this becomes a problem.
        # For now, proceed, but this indicates a potential logic error elsewhere.

    # Map related_id to the canonical origin_id
    trigger_id_mapping[related_id] = origin_id
    logger.debug(f"注册ID映射: {related_id} -> {origin_id}")

    # Ensure the canonical origin_id maps to itself
    if origin_id not in trigger_id_mapping or trigger_id_mapping[origin_id] != origin_id :
         trigger_id_mapping[origin_id] = origin_id
         logger.debug(f"注册ID自映射: {origin_id} -> {origin_id}")

    # If origin_id is a UUID, also map its non-hyphenated version to itself (the hyphenated one)
    if len(origin_id) == 36 and '-' in origin_id:
        origin_id_no_hyphens = origin_id.replace('-', '')
        if origin_id_no_hyphens not in trigger_id_mapping or trigger_id_mapping[origin_id_no_hyphens] != origin_id:
            trigger_id_mapping[origin_id_no_hyphens] = origin_id
            logger.debug(f"注册ID映射 (无连字符): {origin_id_no_hyphens} -> {origin_id}")

def get_original_trigger_id(any_id: str) -> str:
    """通过任何关联ID获取原始的、带连字符的UUID触发ID"""
    global trigger_id_mapping
    
    # First, get the direct mapping. This might be the final origin_id or an intermediate one.
    mapped_value = trigger_id_mapping.get(any_id, any_id)
    
    # If the mapped_value itself is a key that points to a different origin_id (e.g. a chain),
    # resolve it further. We expect origin_ids to map to themselves.
    # This loop handles cases where related_id -> intermediate_id -> origin_id.
    # And ensures that if any_id is already an origin_id, it returns itself.
    visited = {any_id}
    current_lookup = mapped_value
    while current_lookup in trigger_id_mapping and trigger_id_mapping[current_lookup] != current_lookup:
        current_lookup = trigger_id_mapping[current_lookup]
        if current_lookup in visited: # Break circular dependencies
            logger.error(f"Circular dependency detected in trigger_id_mapping for ID: {any_id}")
            return any_id # Fallback to prevent infinite loop
        visited.add(current_lookup)
        
    # At this point, current_lookup should be the canonical origin_id or the original any_id if no mapping found.
    # Ensure what we return is indeed the *original* (hyphenated UUID) form if possible.
    # If current_lookup is a 32-char ID that maps to a 36-char UUID, that's fine.
    # If current_lookup is a 36-char UUID, it should be the one.
    
    # If the final resolved ID is a 32-char string, check if it has a mapping to a 36-char UUID
    if len(current_lookup) == 32 and '-' not in current_lookup:
        final_origin = trigger_id_mapping.get(current_lookup, current_lookup)
        return final_origin
        
    return current_lookup

def register_callback(trigger_id: str, callback_type: str = "generate") -> None:
    """注册一个新的任务回调
    
    Args:
        trigger_id: 任务触发ID
        callback_type: 任务类型(generate, upscale等)
    """
    task_callbacks[trigger_id] = {
        "type": callback_type,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "result": None
    }
    logger.debug(f"已注册任务回调: {trigger_id} ({callback_type})")

def update_callback(trigger_id: str, status: str, data: Dict[str, Any] = None) -> None:
    """更新任务回调状态
    
    Args:
        trigger_id: 任务触发ID
        status: 新状态(pending, generating, completed, failed)
        data: 相关数据
    """
    if trigger_id not in task_callbacks:
        logger.warning(f"尝试更新未注册的回调: {trigger_id}")
        register_callback(trigger_id, "unknown")
        
    task_callbacks[trigger_id]["status"] = status
    task_callbacks[trigger_id]["updated_at"] = datetime.now().isoformat()
    
    if data:
        # 合并或更新数据
        if "result" not in task_callbacks[trigger_id] or not task_callbacks[trigger_id]["result"]:
            task_callbacks[trigger_id]["result"] = {}
            
        task_callbacks[trigger_id]["result"].update(data)
    
    logger.debug(f"更新任务回调: {trigger_id} → {status}")

def get_callback(trigger_id: str) -> Optional[Dict[str, Any]]:
    """获取任务回调数据
    
    Args:
        trigger_id: 任务触发ID
        
    Returns:
        任务回调数据或None
    """
    return task_callbacks.get(trigger_id)

def cleanup_callback(trigger_id: str = None, timeout_minutes: int = 60) -> None:
    """清理旧的回调数据
    
    Args:
        trigger_id: 可选的特定触发ID
        timeout_minutes: 数据保留时间(分钟)
    """
    if trigger_id and trigger_id in task_callbacks:
        logger.debug(f"清理回调数据: {trigger_id}")
        task_callbacks.pop(trigger_id, None)
        return
        
    # 清理所有旧数据
    now = datetime.now()
    to_remove = []
    
    for tid, data in task_callbacks.items():
        updated = datetime.fromisoformat(data["updated_at"])
        if (now - updated).total_seconds() > timeout_minutes * 60:
            to_remove.append(tid)
            
    for tid in to_remove:
        task_callbacks.pop(tid, None)
        
    if to_remove:
        logger.debug(f"已清理 {len(to_remove)} 个过期回调")

# 修改现有的send_callback函数
async def send_callback(trigger_id: str, status: str, data: dict = None, retry: int = 3):
    """发送回调到webhook URL并更新本地状态
    
    Args:
        trigger_id: 任务触发ID
        status: 任务状态(started, generating, completed, failed等)
        data: 要包含的附加数据
        retry: 重试次数
    """
    # 确保trigger_id已注册
    if trigger_id not in task_callbacks:
        register_callback(trigger_id)
    
    # 更新本地状态 - 维持一致性
    api_status = status
    if status == "started" or status == "accepted":
        api_status = "pending"
    elif status in ["completed", "image_ready", "end"]:
        api_status = "completed"
    elif status in ["failed", "error"]:
        api_status = "failed"
    elif status in ["generating", "in_progress"]:
        api_status = "generating"
    else:
        api_status = "generating"
        
    # 只有在状态更高级别时才更新 (pending < generating < completed/failed)
    current_status = task_callbacks.get(trigger_id, {}).get("status")
    should_update = True
    
    # 状态优先级: pending < generating < completed/failed
    if current_status == "completed" and api_status in ["pending", "generating"]:
        should_update = False  # 不要从completed退回到更低级别
        logger.debug(f"忽略状态降级: {trigger_id} [{current_status}] → [{api_status}]")
    elif current_status == "failed" and api_status in ["pending", "generating"]:
        should_update = False  # 不要从failed退回到更低级别
        logger.debug(f"忽略状态降级: {trigger_id} [{current_status}] → [{api_status}]")
    elif current_status == "generating" and api_status == "pending":
        should_update = False  # 不要从generating退回到pending
        logger.debug(f"忽略状态降级: {trigger_id} [{current_status}] → [{api_status}]")
    
    # 特殊情况：如果接收到end状态的回调，表示确实完成，始终设为完成
    if status == "end":
        should_update = True
        api_status = "completed"
        logger.debug(f"收到最终结果，强制更新状态: {trigger_id} → completed")
    
    if should_update:
        update_callback(trigger_id, api_status, data)
    else:
        logger.debug(f"忽略状态更新(保持当前状态): {trigger_id} → {current_status} (忽略 {api_status})")
        # 仍然更新数据，但不改变状态
        if data:
            update_callback(trigger_id, current_status, data)
    
    # 其余代码保持不变
    if not CALLBACK_URL:
        return

    # 添加到payload中以便后续处理
    payload = {
        "trigger_id": trigger_id,
        "status": status,
        "timestamp": datetime.now().isoformat()
    }
    
    # 如果data中包含message_id，添加映射
    if data and "message_id" in data:
        message_id = str(data["message_id"])
        if message_id and message_id != trigger_id:
            register_mapping(trigger_id, message_id)
            logger.info(f"注册Discord消息ID映射: {message_id} -> {trigger_id}")

    if data:
        # Handle image data specially
        if "image_base64" in data:
            payload["image_base64"] = data.pop("image_base64")
        payload["data"] = data

    logger.debug(f"Preparing callback for trigger {trigger_id}: {status}")

    connector = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=30)

    for attempt in range(retry):
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.post(CALLBACK_URL, json=payload, proxy=PROXY_URL) as response:
                    response_text = await response.text()
                    if response.status != 200:
                        logger.error(f"Callback attempt {attempt + 1} failed: {response_text}")
                        if attempt == retry - 1:
                            logger.error(f"All callback attempts failed for trigger {trigger_id}")
                    else:
                        logger.info(f"Callback sent successfully: {trigger_id} - {status}")
                        return
        except Exception as e:
            logger.error(f"Callback attempt {attempt + 1} error: {str(e)}")
            if attempt == retry - 1:
                logger.error(f"All callback attempts failed for trigger {trigger_id}")
        
        if attempt < retry - 1:
            await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff

# API URLs
TRIGGER_URL = "https://discord.com/api/v9/interactions"
UPLOAD_ATTACHMENT_URL = f"https://discord.com/api/v9/channels/{CHANNEL_ID}/attachments"
SEND_MESSAGE_URL = f"https://discord.com/api/v9/channels/{CHANNEL_ID}/messages"

# Headers
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": USER_TOKEN
}

# API Schema
class TriggerType(str, Enum):
    generate = "generate"
    upscale = "upscale"
    variation = "variation"
    solo_variation = "solo_variation" 
    solo_low_variation = "solo_low_variation"
    solo_high_variation = "solo_high_variation"
    max_upscale = "max_upscale"
    reset = "reset"
    describe = "describe"
    expand = "expand"
    zoomout = "zoomout"

class TriggerImagineIn(BaseModel):
    prompt: str
    picurl: Optional[str] = None

class TriggerUVIn(BaseModel):
    index: int
    msg_id: str 
    msg_hash: str
    trigger_id: str

class TriggerResetIn(BaseModel):
    msg_id: str
    msg_hash: str
    trigger_id: str

class TriggerExpandIn(BaseModel):
    msg_id: str
    msg_hash: str
    direction: str
    trigger_id: str

class TriggerZoomOutIn(BaseModel):
    msg_id: str
    msg_hash: str
    zoomout: int
    trigger_id: str

class TriggerDescribeIn(BaseModel):
    upload_filename: str
    trigger_id: str

class TriggerResponse(BaseModel):
    message: str = "success"
    trigger_id: str
    trigger_type: str = ""

class UploadResponse(BaseModel):
    message: str = "success"
    upload_filename: str = ""
    upload_url: str = ""
    trigger_id: str

class SendMessageIn(BaseModel):
    upload_filename: str

class SendMessageResponse(BaseModel):
    message: str = "success"
    picurl: str

# Discord API Client
async def trigger(payload: Dict[str, Any]):
    logger.debug(f"Sending Discord request: {json.dumps(payload, indent=2)}")
    logger.debug(f"Headers: {HEADERS}")
    logger.debug(f"URL: {TRIGGER_URL}")
    
    async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers=HEADERS
    ) as session:
        try:
            async with session.post(TRIGGER_URL, json=payload, proxy=PROXY_URL) as response:
                response_text = await response.text()
                logger.debug(f"Discord response status: {response.status}")
                logger.debug(f"Discord response: {response_text}")
                
                if response.status not in [200, 204]:
                    logger.error(f"Discord API error: {response_text}")
                    return None
                
                # 204 means success with no content
                if response.status == 204:
                    return {"status": "success"}
                    
                return json.loads(response_text)
        except Exception as e:
            logger.error(f"Error calling Discord API: {str(e)}")
            return None

async def upload_attachment(
        filename: str, file_size: int, image: bytes
) -> Union[Dict[str, Union[str, int]], None]:
    payload = {
        "files": [{
            "filename": filename,
            "file_size": file_size,
            "id": "0"
        }]
    }
    async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers=HEADERS
    ) as session:
        async with session.post(UPLOAD_ATTACHMENT_URL, json=payload) as response:
            if response.status != 200:
                return None
            data = await response.json()
            if not data or not data.get("attachments"):
                return None
            attachment = data["attachments"][0]

        # Upload the actual image
        headers = {"Content-Type": "image/png"}
        async with session.put(attachment.get("upload_url"), 
                             data=image, headers=headers) as response:
            return attachment if response.status == 200 else None

async def send_attachment_message(upload_filename: str) -> Union[str, None]:
    payload = {
        "content": "",
        "nonce": "",
        "channel_id": CHANNEL_ID,
        "type": 0,
        "sticker_ids": [],
        "attachments": [{
            "id": "0",
            "filename": upload_filename.split("/")[-1],
            "uploaded_filename": upload_filename
        }]
    }
    async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers=HEADERS
    ) as session:
        async with session.post(SEND_MESSAGE_URL, json=payload) as response:
            if response.status != 200:
                return None
            data = await response.json()
            if not data or not data.get("attachments"):
                return None
            attachment = data["attachments"][0]
            return attachment.get("url")

def _trigger_payload(type_: int, data: Dict[str, Any], trigger_id_for_nonce: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    payload = {
        "type": type_,
        "application_id": "936929561302675456", # Midjourney App ID
        "guild_id": GUILD_ID,
        "channel_id": CHANNEL_ID,
        "session_id": "cb06f61453064c0983f2adae2a88c223", # This seems static, might need to be dynamic
        "data": data
    }
    if trigger_id_for_nonce:
        # Discord nonce max length is 32. UUID without hyphens is 32 chars.
        nonce_value = str(trigger_id_for_nonce).replace('-', '')
        if len(nonce_value) > 32: # Should not happen if input is UUID
            nonce_value = nonce_value[:32]
            logger.warning(f"Nonce value for {trigger_id_for_nonce} was longer than 32 chars after removing hyphens, truncated.")
        payload["nonce"] = nonce_value
        logger.info(f"Using nonce '{nonce_value}' (derived from trigger_id {trigger_id_for_nonce}) for Discord interaction.")

    payload.update(kwargs)
    return payload

# Midjourney Commands
async def generate(prompt: str, trigger_id: str = None, **kwargs):
    if trigger_id:
        # 注册回调
        register_callback(trigger_id, "generate")
        await send_callback(trigger_id, "started", {"prompt": prompt})
    
    payload = _trigger_payload(
        type_=2,
        data={
            "version": int(DRAW_VERSION),
            "id": "938956540159881230", # This is the command ID for /imagine
            "name": "imagine",
            "type": 1, # CHAT_INPUT
            "options": [{
                "type": 3, # STRING
                "name": "prompt",
                "value": prompt
            }],
            "attachments": []
        },
        trigger_id_for_nonce=trigger_id # Pass trigger_id to be used as nonce
    )
    
    result = await trigger(payload)
    if trigger_id:
        try:
            # 修改：Discord返回204表示接受了请求，但图像生成尚未开始
            # 此时应将状态标记为"generating"而非"completed"
            status = "accepted" if result else "failed"
            logger.info(f"Generate command result for {trigger_id}: {status}")
            
            # 发送初始回调，包含结果信息
            callback_data = {"result": result}
            if result:
                # 如果有响应信息，将其包含在回调中
                if isinstance(result, dict) and "id" in result:
                    message_id = str(result["id"])
                    callback_data["message_id"] = message_id
                    
                    # 注册Discord消息ID与触发ID的映射
                    if message_id and message_id != trigger_id:
                        register_mapping(trigger_id, message_id)
                        logger.info(f"为generate任务注册ID映射: {message_id} -> {trigger_id}")
            
            # 状态从"started"改为"generating"
            await send_callback(trigger_id, "generating", callback_data)
            logger.info(f"Initial callback sent for {trigger_id}")
            
            # 等待一段时间，使Discord开始处理，但不要等待它完成
            await asyncio.sleep(2)
            
            # 发送状态更新，但不标记为completed
            if status != "failed":
                await send_callback(trigger_id, "in_progress", {"command": "generate"}, retry=3)
                logger.info(f"Progress update sent for {trigger_id}")
                
        except Exception as e:
            logger.error(f"Error in generate callback for {trigger_id}: {str(e)}")
            await send_callback(trigger_id, "error", {"error": str(e)})
    
    return result

async def upscale(index: int, msg_id: str, msg_hash: str, trigger_id: str = None, **kwargs):
    kwargs = {
        "message_flags": 0,
        "message_id": msg_id,
    }
    payload = _trigger_payload(3, {
        "component_type": 2,
        "custom_id": f"MJ::JOB::upsample::{index}::{msg_hash}"
    }, **kwargs)
    
    # 确保trigger_id被注册
    if trigger_id:
        register_callback(trigger_id, "upscale")
    
    result = await trigger(payload)
    try:
        status = "completed" if result else "failed"
        logger.info(f"Upscale command result for {trigger_id}: {status}")
        
        # 如果有触发ID，注册映射关系
        if trigger_id:
            # 注册消息ID映射
            if msg_id:
                register_mapping(trigger_id, msg_id)
                logger.info(f"为upscale任务注册ID映射: {msg_id} -> {trigger_id}")
                
            # 注册哈希值映射
            if msg_hash:
                register_mapping(trigger_id, msg_hash)
                logger.info(f"为upscale任务注册哈希映射: {msg_hash} -> {trigger_id}")
                
            # 尝试预先注册预期的结果哈希
            # 通常Discord的新消息哈希与原始哈希相关但不完全相同
            if msg_hash and len(msg_hash) > 8:
                # 将原始哈希的前8位和后8位分别注册
                prefix = msg_hash[:8]
                suffix = msg_hash[-8:]
                register_mapping(trigger_id, prefix)
                register_mapping(trigger_id, suffix)
                logger.info(f"为upscale任务注册哈希部分映射: {prefix},{suffix} -> {trigger_id}")
                
            # 向bot系统通知该upscale操作
            try:
                # 发送一个额外的请求通知bot记录该操作
                record_url = os.getenv("BOT_OPERATION_URL")
                if record_url:
                    async with aiohttp.ClientSession() as session:
                        await session.post(record_url, json={
                            "operation": "upscale",
                            "hash": msg_hash,
                            "trigger_id": trigger_id,
                            "index": index
                        })
            except Exception as e:
                logger.warning(f"通知bot操作失败: {e}")
        
        # Send operation result callback
        if trigger_id:  # 避免在trigger_id为None时调用
            await send_callback(trigger_id, status, {
                "result": result,
                "command": "upscale",  # 添加命令类型
                "type": "upscale",     # 明确指定为upscale类型
                "index": index,
                "msg_id": msg_id,
                "msg_hash": msg_hash,
                "expecting_new_message": True  # 告知系统需等待新消息
            })
            logger.info(f"Upscale callback sent for {trigger_id}")
        else:
            logger.warning("尝试发送upscale回调但trigger_id为空")
        
    except Exception as e:
        logger.error(f"Error in upscale callback for {trigger_id}: {str(e)}")
        if trigger_id:  # 避免在trigger_id为None时调用
            await send_callback(trigger_id, "error", {"error": str(e)})
        
    return result

async def variation(index: int, msg_id: str, msg_hash: str, trigger_id: str = None, **kwargs):
    kwargs = {
        "message_flags": 0,
        "message_id": msg_id,
    }
    payload = _trigger_payload(3, {
        "component_type": 2,
        "custom_id": f"MJ::JOB::variation::{index}::{msg_hash}"
    }, **kwargs)
    result = await trigger(payload)
    status = "completed" if result else "failed"
    await send_callback(trigger_id, status, {"result": result})
    return result

async def solo_variation(msg_id: str, msg_hash: str, trigger_id: str = None, **kwargs):
    kwargs = {
        "message_flags": 0,
        "message_id": msg_id,
    }
    payload = _trigger_payload(3, {
        "component_type": 2,
        "custom_id": f"MJ::JOB::variation::1::{msg_hash}::SOLO"
    }, **kwargs)
    result = await trigger(payload)
    status = "completed" if result else "failed"
    await send_callback(trigger_id, status, {"result": result})
    return result

async def solo_low_variation(msg_id: str, msg_hash: str, trigger_id: str = None, **kwargs):
    kwargs = {
        "message_flags": 0,
        "message_id": msg_id,
    }
    payload = _trigger_payload(3, {
        "component_type": 2,
        "custom_id": f"MJ::JOB::low_variation::1::{msg_hash}::SOLO"
    }, **kwargs)
    result = await trigger(payload)
    status = "completed" if result else "failed"
    await send_callback(trigger_id, status, {"result": result})
    return result

async def solo_high_variation(msg_id: str, msg_hash: str, trigger_id: str = None, **kwargs):
    kwargs = {
        "message_flags": 0,
        "message_id": msg_id,
    }
    payload = _trigger_payload(3, {
        "component_type": 2,
        "custom_id": f"MJ::JOB::high_variation::1::{msg_hash}::SOLO"
    }, **kwargs)
    result = await trigger(payload)
    status = "completed" if result else "failed"
    await send_callback(trigger_id, status, {"result": result})
    return result

async def expand(msg_id: str, msg_hash: str, direction: str, trigger_id: str = None, **kwargs):
    kwargs = {
        "message_flags": 0,
        "message_id": msg_id,
    }
    payload = _trigger_payload(3, {
        "component_type": 2,
        "custom_id": f"MJ::JOB::pan_{direction}::1::{msg_hash}::SOLO"
    }, **kwargs)
    result = await trigger(payload)
    status = "completed" if result else "failed"
    await send_callback(trigger_id, status, {"result": result})
    return result

async def zoomout(msg_id: str, msg_hash: str, zoomout: int, trigger_id: str = None, **kwargs):
    kwargs = {
        "message_flags": 0,
        "message_id": msg_id,
    }
    payload = _trigger_payload(3, {
        "component_type": 2,
        "custom_id": f"MJ::Outpaint::{zoomout}::1::{msg_hash}::SOLO"
    }, **kwargs)
    result = await trigger(payload)
    if trigger_id:
        status = "completed" if result else "failed"
        await send_callback(trigger_id, status, {"result": result})
    return result

async def reset(msg_id: str, msg_hash: str, trigger_id: str = None, **kwargs):
    kwargs = {
        "message_flags": 0,
        "message_id": msg_id,
    }
    payload = _trigger_payload(3, {
        "component_type": 2,
        "custom_id": f"MJ::JOB::reroll::0::{msg_hash}::SOLO"
    }, **kwargs)
    result = await trigger(payload)
    if trigger_id:
        status = "completed" if result else "failed"
        await send_callback(trigger_id, status, {"result": result})
    return result

async def describe(upload_filename: str, trigger_id: str = None, **kwargs):
    payload = _trigger_payload(2, {
        "version": DRAW_VERSION,  # Use Discord interaction version
        "id": "1092492867185950852",
        "name": "describe",
        "type": 1,
        "options": [
            {
                "type": 11,
                "name": "image",
                "value": 0
            }
        ],
        "attachments": [{
            "id": "0",
            "filename": upload_filename.split("/")[-1],
            "uploaded_filename": upload_filename,
        }]
    })
    result = await trigger(payload)
    if trigger_id:
        status = "completed" if result else "failed"
        await send_callback(trigger_id, status, {"result": result})
    return result