import os
from typing import Optional, Set, Dict, Any
import uuid
from fastapi import FastAPI, UploadFile, HTTPException
from loguru import logger
import uvicorn

from filter import word_filter

from api import (
    TriggerType, TriggerImagineIn, TriggerUVIn, TriggerResetIn,
    TriggerExpandIn, TriggerZoomOutIn, TriggerDescribeIn, 
    TriggerResponse, UploadResponse, SendMessageIn, SendMessageResponse,
    generate, upscale, variation, reset, describe, expand,
    zoomout, solo_variation, solo_low_variation, solo_high_variation,
    upload_attachment, send_attachment_message,
    # 导入回调管理函数
    register_callback, update_callback, get_callback, cleanup_callback,
    # 导入ID映射函数
    register_mapping
)

# 导入新的ID映射工具
import id_mapper

from _queue import taskqueue, QueueFullError

app = FastAPI(title="Midjourney API")

def generate_trigger_id() -> str:
    """Generate unique trigger ID"""
    return str(uuid.uuid4())

def filter_prompt(prompt: str) -> tuple[bool, str, Set[str]]:
    """Filter sensitive words from prompt
    
    Args:
        prompt: Input prompt
        
    Returns:
        tuple: (is_banned, filtered_prompt, found_words)
    """
    is_banned, filtered_prompt, found_words = word_filter.filter_text(prompt)
    
    if is_banned:
        # Report violation
        word_filter.report_violation(prompt, found_words)
        
    return is_banned, filtered_prompt, found_words

@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Welcome to the Midjourney API v0.0.1"}

@app.post("/v1/api/trigger/imagine", response_model=TriggerResponse)
async def trigger_imagine(body: TriggerImagineIn):
    """Generate image from prompt"""
    is_banned, prompt, found_words = filter_prompt(body.prompt)
    if is_banned:
        # TODO: Report banned word usage
        return {"message": "Prompt contains banned words", "trigger_id": "", "trigger_type": ""}
        
    trigger_id = generate_trigger_id()
    trigger_type = TriggerType.generate.value

    # 立即注册回调以便追踪
    register_callback(trigger_id, "generate")
    # 注册为活动任务
    id_mapper.register_task_start(trigger_id)
    
    if body.picurl:
        prompt = f"{body.picurl} {prompt}"
    
    try:
        taskqueue.put(trigger_id, generate, prompt, trigger_id)
    except QueueFullError as e:
        # 清理失败的注册
        cleanup_callback(trigger_id)
        return {"message": str(e), "trigger_id": "", "trigger_type": ""}
        
    return {"trigger_id": trigger_id, "trigger_type": trigger_type}

# 为其他触发器添加相似的注册模式
@app.post("/v1/api/trigger/upscale", response_model=TriggerResponse)
async def trigger_upscale(body: TriggerUVIn):
    """Upscale a generated image"""
    trigger_id = body.trigger_id
    trigger_type = TriggerType.upscale.value
    
    # 注册回调
    register_callback(trigger_id, "upscale")
    
    try:
        # 提取参数，确保正确传递trigger_id
        index = body.index
        msg_id = body.msg_id
        msg_hash = body.msg_hash
        
        # 直接传递参数，确保trigger_id被正确传递
        taskqueue.put(trigger_id, upscale, index, msg_id, msg_hash, trigger_id)
    except QueueFullError as e:
        cleanup_callback(trigger_id)
        return {"message": str(e), "trigger_id": "", "trigger_type": ""}
        
    return {"trigger_id": trigger_id, "trigger_type": trigger_type}

@app.post("/v1/api/trigger/variation", response_model=TriggerResponse)
async def trigger_variation(body: TriggerUVIn):
    """Create variation of an image"""
    trigger_id = body.trigger_id
    trigger_type = TriggerType.variation.value
    
    try:
        taskqueue.put(trigger_id, variation, **body.dict())
    except QueueFullError as e:
        return {"message": str(e), "trigger_id": "", "trigger_type": ""}
        
    return {"trigger_id": trigger_id, "trigger_type": trigger_type}

@app.post("/v1/api/trigger/solo_variation", response_model=TriggerResponse)
async def trigger_solo_variation(body: TriggerUVIn):
    """Create single variation"""
    trigger_id = body.trigger_id
    trigger_type = TriggerType.solo_variation.value
    try:
        taskqueue.put(trigger_id, solo_variation, **body.dict())
    except QueueFullError as e:
        return {"message": str(e), "trigger_id": "", "trigger_type": ""}
        
    return {"trigger_id": trigger_id, "trigger_type": trigger_type}

@app.post("/v1/api/trigger/solo_low_variation", response_model=TriggerResponse)
async def trigger_solo_low_variation(body: TriggerUVIn):
    """Create subtle variation"""
    trigger_id = body.trigger_id
    trigger_type = TriggerType.solo_low_variation.value
    try:
        taskqueue.put(trigger_id, solo_low_variation, **body.dict())
    except QueueFullError as e:
        return {"message": str(e), "trigger_id": "", "trigger_type": ""}
        
    return {"trigger_id": trigger_id, "trigger_type": trigger_type}

@app.post("/v1/api/trigger/solo_high_variation", response_model=TriggerResponse) 
async def trigger_solo_high_variation(body: TriggerUVIn):
    """Create strong variation"""
    trigger_id = body.trigger_id
    trigger_type = TriggerType.solo_high_variation.value
    try:
        taskqueue.put(trigger_id, solo_high_variation, **body.dict())
    except QueueFullError as e:
        return {"message": str(e), "trigger_id": "", "trigger_type": ""}
        
    return {"trigger_id": trigger_id, "trigger_type": trigger_type}

@app.post("/v1/api/trigger/expand", response_model=TriggerResponse)
async def trigger_expand(body: TriggerExpandIn):
    """Expand image in specified direction"""
    trigger_id = body.trigger_id
    trigger_type = TriggerType.expand.value
    try:
        taskqueue.put(trigger_id, expand, **body.dict())
    except QueueFullError as e:
        return {"message": str(e), "trigger_id": "", "trigger_type": ""}
        
    return {"trigger_id": trigger_id, "trigger_type": trigger_type}

@app.post("/v1/api/trigger/zoomout", response_model=TriggerResponse)
async def trigger_zoomout(body: TriggerZoomOutIn):
    """Zoom out image"""
    trigger_id = body.trigger_id 
    trigger_type = TriggerType.zoomout.value
    try:
        taskqueue.put(trigger_id, zoomout, **body.dict())
    except QueueFullError as e:
        return {"message": str(e), "trigger_id": "", "trigger_type": ""}
        
    return {"trigger_id": trigger_id, "trigger_type": trigger_type}

@app.post("/v1/api/trigger/reset", response_model=TriggerResponse)
async def trigger_reset(body: TriggerResetIn):
    """Reset/regenerate image"""
    trigger_id = body.trigger_id
    trigger_type = TriggerType.reset.value
    try:
        taskqueue.put(trigger_id, reset, **body.dict())
    except QueueFullError as e:
        return {"message": str(e), "trigger_id": "", "trigger_type": ""}
        
    return {"trigger_id": trigger_id, "trigger_type": trigger_type}

@app.post("/v1/api/trigger/describe", response_model=TriggerResponse)
async def trigger_describe(body: TriggerDescribeIn):
    """Generate prompt from image"""
    trigger_id = body.trigger_id
    trigger_type = TriggerType.describe.value
    try:
        taskqueue.put(trigger_id, describe, **body.dict())
    except QueueFullError as e:
        return {"message": str(e), "trigger_id": "", "trigger_type": ""}
        
    return {"trigger_id": trigger_id, "trigger_type": trigger_type}

@app.post("/v1/api/trigger/upload", response_model=UploadResponse)
async def trigger_upload(file: UploadFile):
    """Upload image file"""
    if not file.content_type.startswith("image/"):
        return {"message": "File must be an image"}

    trigger_id = generate_trigger_id()
    filename = f"{trigger_id}.jpg"
    
    attachment = await upload_attachment(filename, file.size, await file.read())
    if not (attachment and attachment.get("upload_url")):
        return {"message": "Failed to upload image"}

    return {
        "upload_filename": attachment.get("upload_filename"),
        "upload_url": attachment.get("upload_url"),
        "trigger_id": trigger_id,
    }

@app.post("/v1/api/trigger/message", response_model=SendMessageResponse)
async def trigger_message(body: SendMessageIn):
    """Send image message"""
    picurl = await send_attachment_message(body.upload_filename)
    if not picurl:
        return {"message": "Failed to send message"}

    return {"picurl": picurl}

from pydantic import BaseModel

class CallbackData(BaseModel):
    trigger_id: str
    status: str
    message_id: Optional[str] = None
    content: Optional[str] = None
    image_url: Optional[str] = None
    image_urls: Optional[list] = None
    image_base64: Optional[str] = None
    progress: Optional[str] = None
    preview_url: Optional[str] = None
    components: Optional[bool] = None
    hash: Optional[str] = None
    type: Optional[str] = None
    job_id: Optional[str] = None
    local_paths: Optional[list] = None

@app.post("/v1/api/trigger/callback")
async def handle_callback(data: CallbackData):
    """处理来自bot的回调"""
    logger.info(f"收到回调: {data.trigger_id}: {data.status}")
    
    # 尝试获取原始触发ID
    original_id = id_mapper.get_original_id(data.trigger_id)
    if original_id != data.trigger_id:
        logger.info(f"找到关联映射: {data.trigger_id} -> {original_id}")
    
    # 检查原始ID和数据中的原始ID是否一致
    if hasattr(data, "original_trigger_id") and data.original_trigger_id:
        if data.original_trigger_id != original_id:
            logger.warning(f"数据中原始ID与映射不一致: {data.original_trigger_id} vs {original_id}")
            # 以数据中的为准
            original_id = data.original_trigger_id
            # 更新映射
            id_mapper.register_mapping(original_id, data.trigger_id)
    
    # 同时更新原始ID和当前ID的状态
    ids_to_update = [data.trigger_id]
    if original_id != data.trigger_id:
        ids_to_update.append(original_id)
    
    # 如果是结束状态，注册任务结束
    if data.status == "end":
        id_mapper.register_task_end(original_id)
    
    for current_trigger_id in ids_to_update:
        # 自动注册未知回调(处理遗留情况)
        callback_data = get_callback(current_trigger_id)
        if not callback_data:
            logger.warning(f"收到未注册任务的回调: {current_trigger_id}")
            register_callback(current_trigger_id, "unknown")
        
        # 构建回调数据
        update_data = {}
        
        # 新增关联ID映射信息
        if data.message_id and data.message_id != current_trigger_id:
            register_mapping(original_id or current_trigger_id, data.message_id)
            update_data["message_id"] = data.message_id
            logger.debug(f"从回调中注册ID映射: {data.message_id} -> {original_id or current_trigger_id}")
        
        # 进度更新
        if data.progress:
            update_data["progress"] = data.progress
            
        # 预览图
        if data.preview_url:
            update_data["preview_url"] = data.preview_url
            
        # 最终结果
        if data.status == "end":
            if data.image_url:
                update_data["image_url"] = data.image_url
                
            if data.image_urls:
                update_data["image_urls"] = data.image_urls
                
            if data.hash:
                update_data["hash"] = data.hash
                update_data["job_id"] = data.job_id if data.job_id else f"{data.type}_{data.hash}"
                
            if data.local_paths:
                update_data["local_paths"] = data.local_paths
            
            # 如果有base64图像数据
            if data.image_base64:
                update_data["image_base64"] = data.image_base64
                logger.info(f"收到图像数据: {data.trigger_id}")
    
        # 确定适当的API状态
        api_status = "generating"
        if data.status == "start":
            api_status = "pending"
        elif data.status == "end":
            # 结束状态总是表示任务完成
            api_status = "completed"
            # 任务完成，从队列中释放
            try:
                taskqueue.pop(current_trigger_id)
            except Exception as e:
                logger.warning(f"无法从队列中释放任务 {current_trigger_id}: {str(e)}")
                
        elif data.status == "completed" or data.status == "image_ready":
            # 获取操作类型
            operation_type = callback_data.get("type") if callback_data else ""
            
            # 检查是否有图像结果
            has_image = (data.image_url is not None or 
                         (data.image_urls is not None and len(data.image_urls) > 0) or
                         data.image_base64 is not None)
            
            # 某些操作类型不需要图像结果也可以标记为完成
            needs_image = operation_type not in ["upscale", "variation", "reset"]
            
            if has_image or not needs_image:
                api_status = "completed"
                # 任务完成，从队列中释放
                try:
                    taskqueue.pop(current_trigger_id)
                except Exception as e:
                    logger.warning(f"无法从队列中释放任务 {current_trigger_id}: {str(e)}")
            else:
                # 如果需要图像但没有，则保持在生成中状态
                api_status = "generating"
                logger.info(f"标记为completed但尚无图像，保持为generating状态: {data.trigger_id}")
        
        elif data.status == "error" or data.status == "failed":
            api_status = "failed"
            # 任务失败，从队列中释放
            try:
                taskqueue.pop(current_trigger_id)
            except Exception as e:
                logger.warning(f"无法从队列中释放任务 {current_trigger_id}: {str(e)}")
                
        # 检查状态优先级，避免状态降级
        current_status = callback_data.get("status") if callback_data else None
        should_update = True
        
        # 状态优先级: pending < generating < completed/failed
        if current_status == "completed" and api_status in ["pending", "generating"]:
            logger.info(f"忽略状态降级: {data.trigger_id} [{current_status}] → [{api_status}]")
            should_update = False
        elif current_status == "failed" and api_status in ["pending", "generating"]:
            logger.info(f"忽略状态降级: {data.trigger_id} [{current_status}] → [{api_status}]")
            should_update = False
        elif current_status == "generating" and api_status == "pending":
            logger.info(f"忽略状态降级: {data.trigger_id} [{current_status}] → [{api_status}]")
            should_update = False
        
        # 数据始终更新，但状态可能不变
        if should_update:
            update_callback(current_trigger_id, api_status, update_data)
        else:
            # 仅更新数据，保留当前状态
            if update_data:
                update_callback(current_trigger_id, current_status, update_data)
    
    return {"status": "success"}

# 添加获取任务状态的API端点
@app.get("/v1/api/status/{trigger_id}")
async def get_task_status(trigger_id: str):
    """获取任务状态"""
    task_data = get_callback(trigger_id)
    if not task_data:
        raise HTTPException(status_code=404, detail=f"未找到ID为{trigger_id}的任务")
        
    return {
        "trigger_id": trigger_id,
        "status": task_data.get("status", "unknown"),
        "type": task_data.get("type", ""),
        "created_at": task_data.get("created_at"),
        "updated_at": task_data.get("updated_at"),
        "result": task_data.get("result", {})
    }

# 定期清理回调数据的端点
@app.post("/v1/api/maintenance/cleanup")
async def cleanup_tasks(minutes: int = 60):
    """清理旧的任务回调数据"""
    cleanup_callback(None, minutes)
    return {"status": "success"}

# 添加这个新的端点到main.py中，放在其他端点之后
@app.get("/v1/api/id_mapping/{any_id}")
async def get_id_mapping(any_id: str):
    """获取ID映射关系"""
    original_id = id_mapper.get_original_id(any_id)
    related_ids = id_mapper.find_related_ids(original_id)
    
    return {
        "original_id": original_id,
        "query_id": any_id,
        "is_original": original_id == any_id,
        "related_ids": list(related_ids)
    }

# 添加一个新端点用于注册ID映射关系
@app.post("/v1/api/id_mapping/register")
async def register_id_mapping(data: Dict[str, str]):
    """手动注册ID映射关系"""
    if not data.get("primary_id") or not data.get("related_id"):
        raise HTTPException(status_code=400, detail="需要提供primary_id和related_id")
        
    primary_id = data["primary_id"]
    related_id = data["related_id"]
    
    # 在API和ID映射器中都注册
    try:
        register_mapping(primary_id, related_id)
        id_mapper.register_mapping(primary_id, related_id)
        logger.info(f"手动注册ID映射: {related_id} -> {primary_id}")
        
        return {
            "status": "success",
            "message": f"成功注册映射: {related_id} -> {primary_id}"
        }
    except Exception as e:
        logger.error(f"注册ID映射失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"注册映射失败: {str(e)}")

# 添加一个实际能返回Discord最近消息的端点
@app.get("/v1/api/discord/recent_messages")
async def get_recent_discord_messages(limit: int = 5):
    """获取Discord频道最近的消息"""
    try:
        # 创建一个简单的存储机制来记录最近消息
        global recent_discord_messages
        
        if not hasattr(app.state, "recent_discord_messages"):
            app.state.recent_discord_messages = []
            
        # 返回存储的最近消息
        recent_msgs = app.state.recent_discord_messages[-limit:]
        return recent_msgs
    except Exception as e:
        logger.error(f"获取Discord消息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取消息失败: {str(e)}")

# 添加一个端点用于bot提交消息
@app.post("/v1/api/discord/submit_message")
async def submit_discord_message(message: Dict[str, Any]):
    """接收来自bot的Discord消息"""
    try:
        # 确保消息具有必要的字段
        required = ["id", "content"]
        if not all(field in message for field in required):
            raise HTTPException(status_code=400, detail="消息必须包含id和content字段")
            
        # 初始化存储
        if not hasattr(app.state, "recent_discord_messages"):
            app.state.recent_discord_messages = []
        
        # 添加消息到存储
        app.state.recent_discord_messages.append(message)
        
        # 只保留最近100条消息
        if len(app.state.recent_discord_messages) > 100:
            app.state.recent_discord_messages = app.state.recent_discord_messages[-100:]
            
        logger.info(f"记录了Discord消息: {message['id']}")
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交Discord消息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"提交消息失败: {str(e)}")

def init_app():
    """初始化应用程序"""
    # Load configuration
    os.environ.setdefault("CONCUR_SIZE", "9999")
    os.environ.setdefault("WAIT_SIZE", "9999")
    
    # Configure logging
    logger.add("app.log", rotation="500 MB")
    
    return app

if __name__ == "__main__":
    app = init_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)