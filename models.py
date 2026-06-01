from sqlalchemy import Column, Integer, String, ForeignKey, Table, DateTime, Index
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

# جدول المفضلة (علاقة متعدد لمتعدد)
favorites = Table(
    'favorites',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id')),
    Column('lecture_id', Integer, ForeignKey('lectures.id'))
)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)  # فهرس للبحث السريع عن المستخدم
    username = Column(String)
    full_name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    favorite_lectures = relationship('Lecture', secondary=favorites, back_populates='favorited_by')
    
    __table_args__ = (
        Index('idx_telegram_id', 'telegram_id'),  # فهرس إضافي للأداء العالي
    )

class Year(Base):
    __tablename__ = 'years'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, index=True)  # فهرس للبحث عن السنة
    
    subjects = relationship('Subject', back_populates='year', cascade='all, delete-orphan')

class Subject(Base):
    __tablename__ = 'subjects'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, index=True)  # فهرس للبحث عن المادة
    year_id = Column(Integer, ForeignKey('years.id'), index=True)  # فهرس للربط السريع مع السنة
    
    year = relationship('Year', back_populates='subjects')
    lectures = relationship('Lecture', back_populates='subject', cascade='all, delete-orphan')
    
    __table_args__ = (
        Index('idx_year_id', 'year_id'),  # فهرس مركب للبحث السريع
        Index('idx_subject_name', 'name'),  # فهرس للبحث عن اسم المادة
    )

class Lecture(Base):
    __tablename__ = 'lectures'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False, index=True)  # فهرس للبحث عن المحاضرة
    file_id = Column(String)  # Telegram file_id for PDF
    subject_id = Column(Integer, ForeignKey('subjects.id'), index=True)  # فهرس للربط السريع مع المادة
    download_count = Column(Integer, default=0, index=True)  # فهرس للترتيب حسب التحميلات
    
    subject = relationship('Subject', back_populates='lectures')
    favorited_by = relationship('User', secondary=favorites, back_populates='favorite_lectures')
    
    __table_args__ = (
        Index('idx_subject_id', 'subject_id'),  # فهرس للبحث السريع عن محاضرات المادة
        Index('idx_lecture_title', 'title'),  # فهرس للبحث عن اسم المحاضرة
        Index('idx_download_count', 'download_count'),  # فهرس للترتيب حسب التحميلات
    )
