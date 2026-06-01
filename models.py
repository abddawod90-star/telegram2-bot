from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Table, DateTime, Index
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
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String)
    full_name = Column(String)
    is_admin = Column(Boolean, default=False)
    is_owner = Column(Boolean, default=False)
    can_add_subject = Column(Boolean, default=False)
    can_delete_subject = Column(Boolean, default=False)
    can_add_lecture = Column(Boolean, default=False)
    can_delete_lecture = Column(Boolean, default=False)
    can_send_broadcast = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    favorite_lectures = relationship('Lecture', secondary=favorites, back_populates='favorited_by')

    __table_args__ = (
        Index('idx_telegram_id', 'telegram_id'),
    )

class Year(Base):
    __tablename__ = 'years'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, index=True)

    subjects = relationship('Subject', back_populates='year', cascade='all, delete-orphan')

class Subject(Base):
    __tablename__ = 'subjects'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, index=True)
    year_id = Column(Integer, ForeignKey('years.id'), index=True)
    specialization = Column(String)
    semester = Column(String)

    year = relationship('Year', back_populates='subjects')
    lectures = relationship('Lecture', back_populates='subject', cascade='all, delete-orphan')

    __table_args__ = (
        Index('idx_year_id', 'year_id'),
        Index('idx_subject_name', 'name'),
    )

class Lecture(Base):
    __tablename__ = 'lectures'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False, index=True)
    file_id = Column(String)
    subject_id = Column(Integer, ForeignKey('subjects.id'), index=True)
    lecture_type = Column(String, default='theoretical')
    download_count = Column(Integer, default=0, index=True)

    subject = relationship('Subject', back_populates='lectures')
    favorited_by = relationship('User', secondary=favorites, back_populates='favorite_lectures')

    __table_args__ = (
        Index('idx_subject_id', 'subject_id'),
        Index('idx_lecture_title', 'title'),
        Index('idx_download_count', 'download_count'),
    )

class Setting(Base):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False, index=True)
    value = Column(String)

