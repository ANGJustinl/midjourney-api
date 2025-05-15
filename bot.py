import os
from enum import Enum
import json
import aiohttp
import asyncio
import base64
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from discord import Intents, Message
from discord.ext import commands
from loguru import logger


def clean_env_value(value: str) -> str:
    """Clean environment variable value by removing quotes and comments"""
    if not value:
        return value
    # Remove comments
    value = value.split('#')[0].strip()
    # Remove quotes
    value = value.strip('"\'')
    return value

# Configuration
BOT_TOKEN = clean_env_value(os.getenv("DISCORD_BOT_TOKEN"))
PROXY_URL = clean_env_value(os.getenv("PROXY_URL"))
CHANNEL_ID = int(clean_env_value(os.getenv("DISCORD_CHANNEL_ID")))

# Create images directory if not exists
IMAGES_DIR = Path("images")
IMAGES_DIR.mkdir(exist_ok=True)
logger.info(f"Images directory: {IMAGES_DIR}")

# Bot setup
intents = Intents.none()
intents.guilds = True  # For server events
intents.guild_messages = True  # For message events
intents.message_content = True  # For reading message content
bot = commands.Bot(command_prefix="", intents=intents, proxy=PROXY_URL)

# Log intents configuration
logger.debug(f"Bot intents: {intents.value}")

class TriggerStatus(str, Enum):
    start = "start"
    generating = "generating"
    end = "end"
    error = "error"
    banned = "banned"
    text = "text"

# Temporary storage for tracking message status
temp_storage: Dict[str, Any] = {}

def set_temp(trigger_id: str) -> None:
    """Store trigger ID in temporary storage"""
    temp_storage[trigger_id] = True

def pop_temp(trigger_id: str) -> None:
    """Remove trigger ID from temporary storage"""
    temp_storage.pop(trigger_id, None)

def get_temp(trigger_id: str) -> Optional[bool]:
    """Get trigger ID status from temporary storage"""
    return temp_storage.get(trigger_id)

def match_trigger_id(content: str) -> Optional[str]:
    """Extract trigger ID from message content"""
    if not content:
        return None
    
    # Example: **[91e22ae8-c6f7-4a04-894d-deb76f8d9b4f] Job queued**
    if content.startswith("**[") and "]" in content:
        return content[3:content.index("]")]
    return None

async def download_image(url: str, filename: str) -> str:
    """Download image from URL and save to images directory"""
    filepath = IMAGES_DIR / filename
    
    connector = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=30)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.81 Safari/537.36'
            }
            async with session.get(url, proxy=PROXY_URL, headers=headers) as response:
                if response.status == 200:
                    content = await response.read()
                    filepath.write_bytes(content)
                    logger.info(f"Image downloaded: {filepath}")
                    return str(filepath)
                else:
                    logger.error(f"Failed to download image ({response.status}): {url}")
                    return None
        except Exception as e:
            logger.error(f"Error downloading image: {str(e)}")
            return None
        finally:
            await session.close()

async def download_all_images(urls: List[str], base_filename: str) -> List[str]:
    """Download multiple images with numbered filenames"""
    if not urls:
        logger.warning("No URLs provided for download")
        return []

    tasks = []
    for i, url in enumerate(urls):
        filename = f"{base_filename}_{i+1}.webp"
        tasks.append(download_image(url, filename))
    
    logger.info(f"Downloading {len(urls)} images with base filename: {base_filename}")
    return await asyncio.gather(*tasks)

async def callback_trigger(trigger_id: str, status: str, message: Message, extra_data: dict = None) -> None:
    """Send callback for trigger status updates"""
    if not os.getenv("CALLBACK_URL"):
        logger.warning("No callback URL configured, skipping callback")
        return

    # Base data structure
    data = {
        "trigger_id": trigger_id,
        "status": status,
        "message_id": str(message.id),
        "content": message.content
    }
    
    # Handle different status types
    if status == TriggerStatus.generating.value:
        if extra_data:
            data.update({
                "progress": extra_data.get("progress"),
                "preview_url": extra_data.get("preview_url")
            })
    elif status == TriggerStatus.end.value:
        if message.attachments:
            data["image_url"] = message.attachments[0].url
            
        # Include extra data (button info, local paths etc.)
        if extra_data:
            data.update(extra_data)
            
            # Convert local image to base64 if available
            if "local_paths" in extra_data and extra_data["local_paths"]:
                try:
                    image_path = Path(extra_data["local_paths"][0])
                    if image_path.exists():
                        with open(image_path, "rb") as f:
                            img_bytes = f.read()
                            img_base64 = base64.b64encode(img_bytes).decode('utf-8')
                            data["image_base64"] = img_base64
                            logger.info(f"Added base64 image data for {image_path}")
                except Exception as e:
                    logger.error(f"Failed to encode image as base64: {str(e)}")
    
    # Log the callback data (truncate base64 in logs)
    log_data = data.copy()
    if 'image_base64' in log_data:
        log_data['image_base64'] = f"{log_data['image_base64'][:50]}...{log_data['image_base64'][-50:]}"
    logger.info(f"Trigger callback [{status}]: {json.dumps(log_data, indent=2)}")

    # Send callback with retries
    async def send_callback_request(session, attempt):
        try:
            async with session.post(
                os.getenv("CALLBACK_URL"),
                json=data,
                proxy=PROXY_URL,
                timeout=30
            ) as response:
                if response.status == 200:
                    logger.info(f"Callback successful for {trigger_id}")
                    return True
                else:
                    resp_text = await response.text()
                    logger.error(f"Callback attempt {attempt + 1} failed: {resp_text}")
                    return False
        except Exception as e:
            logger.error(f"Callback attempt {attempt + 1} error: {str(e)}")
            return False

    connector = aiohttp.TCPConnector(ssl=False)
    retry_count = 3

    async with aiohttp.ClientSession(connector=connector) as session:
        for attempt in range(retry_count):
            success = await send_callback_request(session, attempt)
            if success:
                return
            
            if attempt < retry_count - 1:
                await asyncio.sleep(1 * (attempt + 1))
                continue
            
        logger.error(f"All callback attempts failed for {trigger_id}")

@bot.event
async def on_ready():
    """Bot ready event handler"""
    logger.success(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Monitoring channel: {CHANNEL_ID}")

def get_button_info(message: Message) -> dict:
    """Extract button information from message components"""
    if not message.components:
        return {}
        
    button_info = {}
    
    # 添加消息ID，这对后续操作很重要
    button_info['message_id'] = str(message.id)
    
    # 遍历所有组件行和按钮，提取关键信息
    for row in message.components:
        for btn in row.children:
            if not hasattr(btn, 'custom_id') or not btn.custom_id:
                continue
                
            # Button format: MJ::JOB::type::index::hash[::SOLO]
            if '::' in btn.custom_id:
                parts = btn.custom_id.split('::')
                if len(parts) >= 5:
                    button_info['hash'] = parts[-1] if parts[-1] != "SOLO" else parts[-2]
                    button_info['type'] = parts[2]
                    button_info['index'] = parts[3] if len(parts) > 3 else "1"
                    button_info['job_id'] = f"{button_info['type']}_{button_info['hash']}"
                    button_info['custom_id'] = btn.custom_id
                    logger.debug(f"Extracted button info: {button_info}")
                    # 一旦找到有效按钮信息就返回，避免覆盖
                    if 'hash' in button_info and button_info['hash']:
                        return button_info
    
    # 如果常规按钮解析失败，尝试其他解析方式
    for row in message.components:
        for btn in row.children:
            # 尝试从URL按钮提取信息
            if hasattr(btn, 'url') and btn.url and 'midjourney.com/jobs/' in btn.url:
                job_id = btn.url.split('/')[-1]
                if job_id:
                    button_info['hash'] = job_id
                    button_info['type'] = 'web'
                    button_info['job_id'] = f"web_{job_id}"
                    logger.debug(f"Extracted job ID from URL: {job_id}")
                    return button_info
    
    # 如果没有找到按钮信息，尝试从消息内容中提取
    content = message.content
    hash_match = None
    
    # 尝试从内容中提取哈希值 
    if "Job ID:" in content:
        hash_match = content.split("Job ID:")[1].strip().split()[0]
    elif "jobID:" in content:
        hash_match = content.split("jobID:")[1].strip().split()[0]
    
    if hash_match:
        button_info['hash'] = hash_match
        button_info['type'] = 'unknown'
        button_info['job_id'] = f"unknown_{hash_match}"
        
    return button_info

# 维护一个最近执行的操作类型记录，用于关联后续消息
recent_operations = {
    "upscale": [],
    "variation": [],
    "generate": []
}
MAX_RECENT_OPS = 10  # 每种操作类型最多保留的记录数

def record_operation(op_type: str, hash_value: str, trigger_id: str):
    """记录最近执行的操作，用于后续关联新消息"""
    global recent_operations
    # 将新操作添加到列表开头
    recent_operations[op_type] = [(hash_value, trigger_id, datetime.now())] + recent_operations.get(op_type, [])
    # 限制列表长度
    if len(recent_operations[op_type]) > MAX_RECENT_OPS:
        recent_operations[op_type] = recent_operations[op_type][:MAX_RECENT_OPS]
    logger.info(f"记录{op_type}操作: {hash_value} -> {trigger_id}")

def find_related_operation(new_hash: str) -> Optional[tuple[str, str, str]]:
    """根据新的哈希值查找可能关联的最近操作"""
    # 按时间倒序检查所有最近的操作
    all_ops = []
    for op_type, ops in recent_operations.items():
        all_ops.extend([(op_type, h, tid, dt) for h, tid, dt in ops])
    
    # 按时间排序，最新的优先
    all_ops.sort(key=lambda x: x[3], reverse=True)
    
    # 首先尝试直接匹配哈希值的前缀或后缀
    for op_type, hash_value, trigger_id, _ in all_ops:
        if hash_value[:8] in new_hash or hash_value[-8:] in new_hash:
            logger.info(f"找到哈希部分匹配: 新哈希{new_hash} ~ 旧哈希{hash_value} -> {op_type}操作 {trigger_id}")
            return op_type, hash_value, trigger_id
    
    # 如果没有找到匹配，返回最近的一个操作（通常是导致新消息的操作）
    if all_ops:
        op_type, hash_value, trigger_id, _ = all_ops[0]
        logger.warning(f"未找到精确匹配，使用最近操作: {op_type} {trigger_id}")
        return op_type, hash_value, trigger_id
    
    return None

# 增强版ID映射存储
discord_id_mapping = {}
trigger_time_mapping = {}  # 存储触发时间，用于时间接近的任务关联

def map_discord_id(key_id: str, canonical_trigger_id: str):
    """建立各种ID (key_id) 与规范的、带连字符的UUID trigger_id (canonical_trigger_id) 之间的映射。
    key_id: 可以是 discord_message_id, hash, 或不带连字符的nonce.
    canonical_trigger_id: 必须是原始的、带连字符的UUID.
    """
    if not (len(canonical_trigger_id) == 36 and '-' in canonical_trigger_id):
        logger.error(f"map_discord_id 调用错误: canonical_trigger_id '{canonical_trigger_id}' 不是一个有效的带连字符的UUID。")
        # Potentially try to find the canonical form if key_id is a non-hyphenated version
        if len(canonical_trigger_id) == 32 and '-' not in canonical_trigger_id:
            logger.warning(f"Attempting to use '{canonical_trigger_id}' as a non-hyphenated UUID to find its canonical form.")
            # This case should ideally be handled before calling map_discord_id,
            # or find_mapped_trigger_id should be robust enough.
            # For now, we'll assume the caller provides the correct canonical_trigger_id.
            pass # Fall through, but this is a sign of potential issues.

    # 1. 本地 bot.py 映射
    discord_id_mapping[key_id] = canonical_trigger_id
    logger.info(f"[Bot Local Map] 映射: {key_id} -> {canonical_trigger_id}")

    # 确保规范ID自映射 (在bot本地)
    if canonical_trigger_id not in discord_id_mapping or discord_id_mapping[canonical_trigger_id] != canonical_trigger_id:
        discord_id_mapping[canonical_trigger_id] = canonical_trigger_id
        logger.info(f"[Bot Local Map] 自映射: {canonical_trigger_id} -> {canonical_trigger_id}")

    # 如果规范ID是UUID，也映射其无连字符版本 (在bot本地)
    if len(canonical_trigger_id) == 36 and '-' in canonical_trigger_id:
        no_hyphen_id = canonical_trigger_id.replace('-', '')
        if no_hyphen_id not in discord_id_mapping or discord_id_mapping[no_hyphen_id] != canonical_trigger_id:
            discord_id_mapping[no_hyphen_id] = canonical_trigger_id
            logger.info(f"[Bot Local Map] 无连字符映射: {no_hyphen_id} -> {canonical_trigger_id}")
            
    # 2. 同步到 API 系统的全局映射
    try:
        from api import register_mapping as api_register_mapping
        # api_register_mapping 期望 origin_id 是规范的 trigger_id
        api_register_mapping(canonical_trigger_id, key_id)
        logger.info(f"[API Global Map] 通过API注册映射: {key_id} -> {canonical_trigger_id}")
    except ImportError:
        logger.error("无法导入 api.register_mapping。API全局映射将不会更新。")
    except Exception as e:
        logger.error(f"调用 api.register_mapping 失败: {e}")
    
    # 3. 记录触发时间 (使用规范ID作为键)
    if canonical_trigger_id not in trigger_time_mapping: # Only record time for new canonical IDs
        trigger_time_mapping[canonical_trigger_id] = datetime.now()
        logger.debug(f"记录 {canonical_trigger_id} 的触发时间: {trigger_time_mapping[canonical_trigger_id]}")

def find_mapped_trigger_id(any_id: str) -> Optional[str]:
    """通过任何关联ID (消息ID, hash, 无连字符nonce) 查找规范的、带连字符的UUID触发ID"""
    logger.debug(f"find_mapped_trigger_id 查找: '{any_id}'")
    
    # 1. 尝试本地 bot.py 映射
    if any_id in discord_id_mapping:
        mapped_value = discord_id_mapping[any_id]
        logger.debug(f"  本地找到直接映射: '{any_id}' -> '{mapped_value}'")
        # 确保返回的是规范形式 (带连字符的UUID)
        # 如果 mapped_value 仍然是一个key (例如无连字符的ID), 则进一步解析
        if mapped_value in discord_id_mapping and discord_id_mapping[mapped_value] == mapped_value: # It's a canonical ID
            return mapped_value
        elif mapped_value in discord_id_mapping: # It's an intermediate key, resolve further
             resolved_further = discord_id_mapping.get(mapped_value, mapped_value)
             logger.debug(f"  本地进一步解析: '{mapped_value}' -> '{resolved_further}'")
             return resolved_further
        return mapped_value # Fallback

    logger.debug(f"  本地未找到 '{any_id}' 的直接映射。")

    # 2. 尝试从 API 系统的全局映射获取
    try:
        from api import get_original_trigger_id as api_get_original_trigger_id
        original_id_from_api = api_get_original_trigger_id(any_id)
        logger.debug(f"  API get_original_trigger_id 返回 for '{any_id}': '{original_id_from_api}'")
        if original_id_from_api != any_id:  # 找到了一个不同于输入的新映射
            # 将API的映射结果存到本地，并确保返回的是规范形式
            map_discord_id(any_id, original_id_from_api) # This will also update API map, but it's fine.
            return original_id_from_api
        # 如果API返回的是any_id本身，说明API侧也没有更深的映射，或者any_id就是规范ID
        # 检查any_id是否已经是规范形式
        if len(any_id) == 36 and '-' in any_id:
             # 可能是API侧只有自映射，但本地没有，现在补充上
             map_discord_id(any_id, any_id)
             return any_id

    except ImportError:
        logger.error("无法导入 api.get_original_trigger_id。无法查询API全局映射。")
    except Exception as e:
        logger.error(f"调用 api.get_original_trigger_id 失败: {e}")
    
    # 3. 如果找不到映射，尝试用时间关联查找最新的 canonical_trigger_id
    # 这个逻辑现在应该更少被触发，因为nonce应该能提供直接关联
    if trigger_time_mapping:
        now = datetime.now()
        # 筛选出最近10分钟内记录的 *规范* trigger_id
        recent_canonical_ids = [(tid, ts) for tid, ts in trigger_time_mapping.items()
                                if (now - ts).total_seconds() < 600 and len(tid) == 36 and '-' in tid]
        
        if recent_canonical_ids:
            recent_canonical_ids.sort(key=lambda x: x[1], reverse=True) #最新的优先
            latest_canonical_id = recent_canonical_ids[0][0]
            logger.warning(f"  启发式推断: 未找到 '{any_id}' 的映射，通过时间关联推断为 -> '{latest_canonical_id}'")
            # 创建新的映射：any_id -> latest_canonical_id
            map_discord_id(any_id, latest_canonical_id)
            return latest_canonical_id
    
    logger.warning(f"  最终未找到 '{any_id}' 的映射。")
    return None

# 增加提交消息到API的函数
async def submit_discord_message(message: Message) -> bool:
    """将Discord消息提交到API系统"""
    api_url_env = os.getenv("API_URL")
    if not api_url_env:
        logger.debug("API_URL not configured, skipping message submission to external API.") # Changed to debug to reduce noise if not used
        return True # Return True to not break the flow, assuming this is optional or handled elsewhere if critical

    # 构建消息数据
    msg_data = {
        "id": str(message.id),
        "content": message.content,
        "components": [],  # 简化组件结构
        "attachments": []
    }
    
    # 处理组件
    if message.components:
        for row in message.components:
            row_data = []
            for btn in row.children:
                btn_data = {}
                # 复制按钮的关键属性
                if hasattr(btn, "custom_id") and btn.custom_id:
                    btn_data["custom_id"] = btn.custom_id
                if hasattr(btn, "url") and btn.url:
                    btn_data["url"] = btn.url
                if hasattr(btn, "label") and btn.label:
                    btn_data["label"] = btn.label
                    
                row_data.append(btn_data)
            msg_data["components"].append({"components": row_data})
    
    # 处理附件
    if message.attachments:
        for attachment in message.attachments:
            msg_data["attachments"].append({
                "id": str(attachment.id),
                "url": attachment.url,
                "filename": attachment.filename
            })
    
    # 提交到API
    try:
        async with aiohttp.ClientSession() as session:
            # Use the validated api_url_env
            api_url_to_submit = f"{api_url_env}/v1/api/discord/submit_message"
            async with session.post(api_url_to_submit, json=msg_data) as response:
                if response.status == 200:
                    logger.debug(f"Successfully submitted message {message.id} to API at {api_url_to_submit}")
                    return True
                else:
                    logger.warning(f"提交消息失败: {response.status}")
                    return False
    except Exception as e:
        logger.error(f"提交消息时出错: {str(e)}")
        return False

@bot.event
async def on_message(message: Message):
    """Message creation event handler"""
    try:
        # Check if message is from Midjourney bot and in correct channel
        if message.author.id != 936929561302675456 or message.channel.id != CHANNEL_ID:
            return

        # 首先将消息提交到API系统
        await submit_discord_message(message)
        
        logger.debug(f"New message: {message.content}")
        
        # 首先尝试从消息内容中提取trigger_id
        # --- Enhanced logging for trigger_id determination ---
        logger.info(f"--- Determining trigger_id for message ID: {message.id} ---")
        # --- Enhanced logging for trigger_id determination ---
        logger.info(f"--- Determining trigger_id for message ID: {message.id} ---")
        
        # 0. Try to get trigger_id from message.nonce (NEW)
        trigger_id_from_nonce = None
        if hasattr(message, 'nonce') and message.nonce:
            trigger_id_from_nonce = str(message.nonce)
            logger.info(f"0. Found nonce in message: {trigger_id_from_nonce}")
            # Check if this nonce is a known trigger_id (it should be if we sent it)
            # We can directly use it if it's a valid UUID format or matches a known pattern.
            # For now, we'll prioritize it if found.
            # We also need to ensure this nonce is actually one of our trigger_ids.
            # A simple check could be to see if it's in api.task_callbacks or id_mapper.
            # For simplicity now, if a nonce exists, we assume it's our trigger_id.
            # TODO: Add validation that nonce is a trigger_id we generated.
            
        trigger_id = trigger_id_from_nonce # Prioritize nonce if available

        if not trigger_id:
            trigger_id = match_trigger_id(message.content)
            logger.info(f"1. match_trigger_id from content (used if no nonce): {trigger_id}")
        else:
            logger.info(f"1. match_trigger_id from content (skipped due to nonce): {match_trigger_id(message.content)}")


        button_info = {}
        if message.components:
            button_info = get_button_info(message)
            logger.info(f"2. get_button_info result: {button_info}")
            
        if not trigger_id and button_info and 'hash' in button_info: # Only if trigger_id not found by nonce or content
            hash_id = button_info['hash']
            logger.info(f"3. Extracted hash_id: {hash_id}")
            
            mapped_id_from_hash = find_mapped_trigger_id(hash_id)
            logger.info(f"4. find_mapped_trigger_id for hash_id '{hash_id}': {mapped_id_from_hash}")
            if mapped_id_from_hash:
                trigger_id = mapped_id_from_hash
                logger.info(f"   Updated trigger_id using mapped_id_from_hash: {trigger_id}")
            else:
                related_op = find_related_operation(hash_id)
                logger.info(f"5. find_related_operation for hash_id '{hash_id}': {related_op}")
                if related_op:
                    op_type, old_hash, related_trigger_id_from_op = related_op
                    trigger_id = related_trigger_id_from_op
                    logger.info(f"   Updated trigger_id using related_op: {trigger_id} (type: {op_type}, old_hash: {old_hash})")
                    map_discord_id(hash_id, trigger_id) # Register new mapping
                        
        if not trigger_id and hasattr(message, "reference") and message.reference: # Only if trigger_id not found yet
            if hasattr(message.reference, "message_id") and message.reference.message_id:
                ref_msg_id = str(message.reference.message_id)
                logger.info(f"6. Found message reference to: {ref_msg_id}")
                mapped_id_from_ref = find_mapped_trigger_id(ref_msg_id)
                logger.info(f"7. find_mapped_trigger_id for ref_msg_id '{ref_msg_id}': {mapped_id_from_ref}")
                if mapped_id_from_ref:
                    trigger_id = mapped_id_from_ref
                    logger.info(f"   Updated trigger_id using mapped_id_from_ref: {trigger_id}")
        
        if not trigger_id: # Only if trigger_id not found yet
            logger.info(f"8. Trigger_id still not found. Trying inference for current message ID: {message.id}")
            inferred_id = find_mapped_trigger_id(str(message.id))
            logger.info(f"9. find_mapped_trigger_id for current message_id '{message.id}': {inferred_id}")
            if inferred_id:
                trigger_id = inferred_id
                logger.info(f"   Updated trigger_id using inferred_id for current message: {trigger_id}")
        
        if trigger_id:
            map_discord_id(str(message.id), trigger_id)
            logger.info(f"FINAL trigger_id for message {message.id}: {trigger_id}")
        else:
            logger.warning(f"FINAL trigger_id for message {message.id} NOT FOUND.")
        # --- End of enhanced logging ---
            logger.warning(f"FINAL trigger_id for message {message.id} NOT FOUND.")
        # --- End of enhanced logging ---
        
        # Handle different message types
        if "Waiting to start" in message.content:
            if trigger_id:
                set_temp(trigger_id)
                await callback_trigger(trigger_id, TriggerStatus.start.value, message)
                logger.info(f"Started job: {trigger_id} (Discord message ID: {message.id})")
            return
        
        if not trigger_id and message.attachments and "(relaxed)" in message.content:
            # Final message without trigger_id
            logger.warning("Final message without trigger_id, using message ID")
            trigger_id = str(message.id)
    
        if not trigger_id:
            logger.warning(f"No trigger_id found for message: {message.content}")
            return
    
        if "(Stopped)" in message.content:
            pop_temp(trigger_id)
            await callback_trigger(trigger_id, TriggerStatus.error.value, message)
            return
    
        # 最终消息处理逻辑优化
        if "(relaxed)" in message.content or message.attachments:
            # 如果没有button_info，尝试获取
            if not button_info and message.components:
                button_info = get_button_info(message)
                
            # 确保消息ID始终包含在回调数据中
            if not button_info:
                button_info = {}
            button_info['message_id'] = str(message.id)
            
            logger.info(f"Processing potential final message with button_info: {button_info}")
            
            # 获取图像URL并下载
            image_urls = []
            if message.attachments:
                image_urls = [a.url for a in message.attachments]
                logger.info(f"Found {len(image_urls)} images to download")
                
                # 如果知道hash，使用它作为基础文件名，否则使用trigger_id或消息ID
                if 'hash' in button_info:
                    base_filename = button_info['hash']
                else:
                    base_filename = trigger_id or str(message.id)
                    
                # 下载图像
                logger.info(f"Downloading images with base filename: {base_filename}")
                local_paths = await download_all_images(image_urls, base_filename)
                if local_paths:
                    button_info['local_paths'] = [p for p in local_paths if p]
                    logger.info(f"Successfully downloaded {len(button_info['local_paths'])} images")
                else:
                    logger.warning("No images were downloaded successfully")
                    
                # 准备回调数据
                data = {
                    "message_id": str(message.id),
                    "image_urls": image_urls,
                    "components": bool(message.components),
                    **button_info
                }
                
                # 如果此时仍然没有触发ID，但找到了hash
                if not trigger_id and 'hash' in button_info:
                    # 最后尝试通过时间接近度找到触发ID
                    trigger_id = find_mapped_trigger_id(button_info['hash'])
                    if not trigger_id:
                        # 如果实在找不到，将消息ID作为触发ID
                        trigger_id = str(message.id)
                        logger.warning(f"Using message ID as trigger_id: {trigger_id}")
                
                await callback_trigger(trigger_id, TriggerStatus.end.value, message, data)
                return

        # Progress update
        if "%" in message.content:
            progress = message.content.split("(")[1].split("%")[0].strip()
            data = {
                "progress": progress,
                "preview_url": message.attachments[0].url if message.attachments else None
            }
            await callback_trigger(trigger_id, TriggerStatus.generating.value, message, data)
            return

        # Unhandled message
        logger.warning(f"Unhandled message: {message.content}")
        pop_temp(trigger_id)
        await callback_trigger(trigger_id, TriggerStatus.end.value, message)
            
    except Exception as e:
        logger.error(f"Failed to process message: {str(e)}\n{message.content}")
        if trigger_id:
            pop_temp(trigger_id)
            await callback_trigger(trigger_id, TriggerStatus.error.value, message)

@bot.event
async def on_message_edit(before: Message, after: Message):
    """Message edit event handler"""
    try:
        if after.author.id != 936929561302675456 or after.channel.id != CHANNEL_ID:
            return

        logger.debug(f"Message edited: {after.content}")
        logger.debug(f"Message components: {after.components}")
        logger.debug(f"Message attachments: {[a.url for a in after.attachments] if after.attachments else 'No attachments'}")
        
        # --- Enhanced logging for trigger_id determination in on_message_edit ---
        logger.info(f"--- Determining trigger_id for EDITED message ID: {after.id} (Before ID: {before.id}) ---")
        # --- Enhanced logging for trigger_id determination in on_message_edit ---
        logger.info(f"--- Determining trigger_id for EDITED message ID: {after.id} (Before ID: {before.id}) ---")
        
        # 0. Try to get trigger_id from EDITED message.nonce (NEW)
        trigger_id_from_nonce_edit = None
        if hasattr(after, 'nonce') and after.nonce:
            trigger_id_from_nonce_edit = str(after.nonce)
            logger.info(f"0. Found nonce in EDITED message: {trigger_id_from_nonce_edit}")
            # TODO: Add validation that nonce is a trigger_id we generated.

        trigger_id = trigger_id_from_nonce_edit # Prioritize nonce if available

        if not trigger_id:
            trigger_id = match_trigger_id(after.content)
            logger.info(f"1. match_trigger_id from EDITED content (used if no nonce): {trigger_id}")
        else:
            logger.info(f"1. match_trigger_id from EDITED content (skipped due to nonce): {match_trigger_id(after.content)}")


        button_info_edit = {}
        if after.components:
            button_info_edit = get_button_info(after)
            logger.info(f"2. get_button_info for EDITED message: {button_info_edit}")

        if not trigger_id and button_info_edit and 'hash' in button_info_edit: # Only if trigger_id not found by nonce or content
            hash_id_edit = button_info_edit['hash']
            logger.info(f"3. Extracted hash_id from EDITED message: {hash_id_edit}")

            mapped_id_from_hash_edit = find_mapped_trigger_id(hash_id_edit)
            logger.info(f"4. find_mapped_trigger_id for EDITED hash_id '{hash_id_edit}': {mapped_id_from_hash_edit}")
            if mapped_id_from_hash_edit:
                trigger_id = mapped_id_from_hash_edit
                logger.info(f"   Updated trigger_id for EDITED message using mapped_id_from_hash: {trigger_id}")
            else:
                related_op_edit = find_related_operation(hash_id_edit)
                logger.info(f"5. find_related_operation for EDITED hash_id '{hash_id_edit}': {related_op_edit}")
                if related_op_edit:
                    op_type_edit, old_hash_edit, related_trigger_id_from_op_edit = related_op_edit
                    trigger_id = related_trigger_id_from_op_edit
                    logger.info(f"   Updated trigger_id for EDITED message using related_op: {trigger_id} (type: {op_type_edit}, old_hash: {old_hash_edit})")
                    map_discord_id(hash_id_edit, trigger_id)
        
        if not trigger_id: # Only if trigger_id not found yet
            logger.info(f"6. Trigger_id for EDITED message still not found. Trying inference for EDITED message ID: {after.id}")
            inferred_id_edit = find_mapped_trigger_id(str(after.id))
            logger.info(f"7. find_mapped_trigger_id for EDITED message_id '{after.id}': {inferred_id_edit}")
            if inferred_id_edit:
                trigger_id = inferred_id_edit
                logger.info(f"   Updated trigger_id for EDITED message using its own mapped ID: {trigger_id}")
        
        if not trigger_id: # Only if trigger_id not found yet
            logger.info(f"8. Trigger_id for EDITED message still not found. Trying inference for BEFORE message ID: {before.id}")
            inferred_id_before = find_mapped_trigger_id(str(before.id))
            logger.info(f"9. find_mapped_trigger_id for BEFORE message_id '{before.id}': {inferred_id_before}")
            if inferred_id_before:
                trigger_id = inferred_id_before
                logger.info(f"   Updated trigger_id for EDITED message using BEFORE message's mapped ID: {trigger_id}")

        if trigger_id:
            map_discord_id(str(after.id), trigger_id)
            logger.info(f"FINAL trigger_id for EDITED message {after.id}: {trigger_id}")
        else:
            if "(relaxed)" in after.content and after.attachments:
                trigger_id = str(after.id)
                logger.warning(f"FINAL trigger_id for EDITED message {after.id} NOT FOUND by other means. Using message ID as trigger_id: {trigger_id}")
                map_discord_id(str(after.id), trigger_id)
            else:
                logger.error(f"FINAL trigger_id for EDITED message {after.id} NOT FOUND and not a clear final message. Returning.")
                return
        # --- End of enhanced logging for on_message_edit ---
                return
        # --- End of enhanced logging for on_message_edit ---

        # Final message with completed image and buttons
        if "(relaxed)" in after.content and "%" not in after.content:
            button_info = get_button_info(after)
            image_urls = [a.url for a in after.attachments] if after.attachments else []
            
            if image_urls:
                base_filename = button_info.get('job_id', trigger_id)
                logger.info(f"[Edit] Downloading images for job {base_filename}")
                local_paths = await download_all_images(image_urls, base_filename)
                button_info['local_paths'] = [p for p in local_paths if p]
                
                if local_paths:
                    logger.info(f"[Edit] Successfully downloaded {len(local_paths)} images")
                    button_info['preview_url'] = image_urls[0]
                else:
                    logger.warning("[Edit] Failed to download any images")
            
            data = {
                "message_id": str(after.id),
                "image_urls": image_urls,
                "components": bool(after.components),
                **button_info
            }
            
            logger.info(f"[Edit] Final image data: {json.dumps(data, indent=2)}")
            pop_temp(trigger_id)
            await callback_trigger(trigger_id, TriggerStatus.end.value, after, data)
            return
        
        # Progress update
        if "%" in after.content:
            progress = after.content.split("(")[1].split("%")[0].strip()
            data = {
                "progress": progress,
                "preview_url": after.attachments[0].url if after.attachments else None
            }
            logger.info(f"[Edit] Progress {progress}% with preview")
            await callback_trigger(trigger_id, TriggerStatus.generating.value, after, data)
            
    except Exception as e:
        error_msg = f"[Edit] Failed to process message: {str(e)}\nContent: {after.content}"
        if hasattr(after, 'attachments'):
            error_msg += f"\nAttachments: {[a.url for a in after.attachments]}"
        logger.error(error_msg)
        
        if trigger_id:
            pop_temp(trigger_id)
            await callback_trigger(trigger_id, TriggerStatus.error.value, after, {"error": str(e)})

def run():
    """Start the bot"""
    if not BOT_TOKEN:
        raise ValueError("Missing required environment variable: DISCORD_BOT_TOKEN")
    
    try:
        logger.info("Starting bot...")
        bot.run(BOT_TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {str(e)}")
        raise

if __name__ == "__main__":
    run()