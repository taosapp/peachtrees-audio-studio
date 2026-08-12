from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from core.database import Base


class TaskRecord(Base):
    __tablename__ = "task_records"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(64), unique=True, nullable=False, index=True)  # 唯一任务UUID
    task_type = Column(String(20), nullable=False, default="subtitle", index=True)  # subtitle / asr / tts
    filename = Column(String(255), nullable=False)
    language = Column(String(10), default="zh")
    status = Column(String(20), default="pending", index=True)   # pending / processing / done / failed
    message = Column(String(500), default="")

    # subtitle 字段
    subtitle_count = Column(Integer, default=0)
    srt_content = Column(Text, nullable=True)
    duration_sec = Column(Float, nullable=True)      # 视频时长（秒）

    # asr 字段
    asr_text = Column(Text, nullable=True)           # 识别出的文字
    asr_segments = Column(Text, nullable=True)       # JSON 字符串，含时间戳分段

    # tts 字段
    voice_name = Column(String(100), nullable=True)  # 使用的音色名
    gen_text = Column(Text, nullable=True)            # 合成的文本
    result_path = Column(String(500), nullable=True) # 合成音频文件路径
    tts_duration_sec = Column(Float, nullable=True)  # 合成音频时长
    sample_rate = Column(Integer, nullable=True)     # 采样率
    elapsed_sec = Column(Float, nullable=True)       # 合成过程耗时（秒，提交→完成）

    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
