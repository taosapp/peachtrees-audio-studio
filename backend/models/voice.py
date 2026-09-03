import uuid
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from core.database import Base


class Voice(Base):
    """音色库模型"""
    __tablename__ = "voices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(String(36), unique=True, nullable=False, index=True, comment="唯一标识符，用于文件命名")
    name = Column(String(100), unique=True, nullable=False, index=True, comment="音色名称")
    ref_audio = Column(String(500), nullable=False, comment="参考音频文件路径（voices/{uuid}.wav）")
    ref_text = Column(Text, nullable=False, comment="参考文本")
    ref_pt = Column(String(500), nullable=True, comment="音色特征文件路径（voices/{uuid}.pt）")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.uuid:
            self.uuid = str(uuid.uuid4())
