"""
模型状态 API
提供各 AI 模型加载状态和进度查询
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1/models", tags=["模型状态"])


class ModelStatus(BaseModel):
    name: str
    loaded: bool
    progress: float  # 0-100
    message: str


@router.get("/status")
async def get_models_status():
    """
    获取所有模型的状态
    - TTS (CosyVoice3): 文本转语音/声音克隆
    """
    # TTS 状态 - 通过检查 worker 是否就绪
    tts_status = _get_tts_status()
    
    return {
        "models": [tts_status],
        "timestamp": None
    }


def _get_tts_status() -> ModelStatus:
    """获取 TTS 模型状态"""
    try:
        import os
        from services.task_lock import get_all_task_status
        from core.config import COSYVOICE_MODEL_DIR as cosyvoice_dir
        
        task_status = get_all_task_status()
        
        if os.path.isdir(cosyvoice_dir):
            has_model = os.path.exists(os.path.join(cosyvoice_dir, "cosyvoice3.yaml"))
            
            if has_model:
                if task_status.get("tts_running"):
                    return ModelStatus(
                        name="CosyVoice3",
                        loaded=True,
                        progress=100,
                        message="正在合成语音中..."
                    )
                else:
                    return ModelStatus(
                        name="CosyVoice3",
                        loaded=True,
                        progress=100,
                        message="模型就绪，可以开始合成"
                    )
        
        return ModelStatus(
            name="CosyVoice3",
            loaded=False,
            progress=0,
            message="模型文件未找到，请下载模型"
        )
    except Exception as e:
        return ModelStatus(
            name="CosyVoice3",
            loaded=False,
            progress=0,
            message=f"错误: {str(e)}"
        )


@router.get("/task-status")
async def get_task_status():
    """获取当前任务运行状态"""
    from services.task_lock import get_all_task_status
    
    status = get_all_task_status()
    
    # 转换任务类型名称
    task_type_map = {
        "tts": "语音合成"
    }
    
    current = status.get("current_task")
    if current:
        current["task_type_name"] = task_type_map.get(current.get("task_type", ""), current.get("task_type", ""))
    
    return {
        "asr_running": False,
        "tts_running": status.get("tts_running", False),
        "current_task": current,
    }