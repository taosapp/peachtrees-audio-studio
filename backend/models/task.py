from sqlalchemy import Column, Integer, String, Text, Float, DateTime, func
from core.database import Base


class TaskRecord(Base):
    """语音合成任务记录"""
    __tablename__ = "task_records"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(64), unique=True, nullable=False, index=True)  # 唯一任务UUID
    task_type = Column(String(20), nullable=False, default="tts", index=True)
    filename = Column(String(255), nullable=False)
    status = Column(String(20), default="pending", index=True)   # pending / processing / done / failed
    message = Column(String(500), default="")

    # tts 字段
    voice_name = Column(String(100), nullable=True)  # 使用的音色名
    gen_text = Column(Text, nullable=True)            # 合成的文本
    result_path = Column(String(500), nullable=True) # 合成音频文件路径
    tts_duration_sec = Column(Float, nullable=True)  # 合成音频时长
    sample_rate = Column(Integer, nullable=True)     # 采样率
    seed = Column(Integer, nullable=True)            # 推理随机种子，用于复现
    elapsed_sec = Column(Float, nullable=True)       # 合成过程耗时（秒，提交→完成）
    progress = Column(Integer, nullable=True)        # 分片合成进度（0-100，仅 processing 阶段有意义）

    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
