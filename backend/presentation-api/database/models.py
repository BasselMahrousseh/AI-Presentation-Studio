from sqlalchemy import Column, Integer, String, ForeignKey, Text
from database.database import Base, get_db


class Project(Base):
    __tablename__ = "AIPS_PROJECT"

    PROJECT_ID = Column(Integer, primary_key=True)
    OWNER_ID = Column(String)
    TEAM_ID = Column(String)
    TITLE = Column(String)
    CLASSIFICATION = Column(String)
    STATUS = Column(String)


class Job(Base):
    __tablename__ = "AIPS_JOB"

    JOB_ID = Column(Integer, primary_key=True)
    PROJECT_ID = Column(Integer, ForeignKey("AIPS_PROJECT.PROJECT_ID"))
    TYPE = Column(String)
    STATUS = Column(String)
    CURRENT_STAGE = Column(String)
    PROGRESS = Column(Integer)