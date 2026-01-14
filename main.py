from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy.orm import Session,declarative_base,sessionmaker
from sqlalchemy import create_engine, Column, Integer, String,ForeignKey,DateTime
from datetime import datetime, timedelta


database_url = "sqlite:///./kikundi.db"

engine = create_engine(database_url,connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    firebase_uid = Column(String, unique=True, index=True)
    full_name = Column(String)
    phone=Column(String, unique=True, index=True)
    created_at = Column(String, default=datetime.utcnow)
    
class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    description = Column(String)
    created_at = Column(String, default=datetime.utcnow)
    created_by = Column(Integer,ForeignKey('users.id'))
    
class GroupMember(Base):
    __tablename__ = "group_members"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey('groups.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    joined_at = Column(String, default=datetime.utcnow)   
    
class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey('groups.id'))
    topic = Column(String)
    meeting_datetime = Column(DateTime)
    created_at = Column(String, default=datetime.utcnow)
    
class Contribution(Base):
    __tablename__ = "contributions"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey('groups.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    amount = Column(Integer)
    contribution_date = Column(String, default=datetime.utcnow)    
    
Base.metadata.create_all(bind=engine)

app = FastAPI()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
 
 
def get_current_user(authorization: str = Header(...), db: Session = Depends(get_db)):
    firebase_uid = authorization.replace("Bearer ", "")
    user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    return user        


@app.post("/groups/")
def create_group(name: str, description: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    group = Group(name=name, description=description, created_by=current_user.id)
    db.add(group)
    db.commit()
    db.refresh(group)
    
    Member = GroupMember(group_id=group.id, user_id=current_user.id)
    db.add(Member)
    db.commit()
    
    
    return group


@app.post("/groups/{group_id}/members/")
def add_group_member(group_id: int, user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    member = GroupMember(group_id=group_id, user_id=user_id)
    db.add(member)
    db.commit()
    db.refresh(member)
    
    return member

@app.post("/groups/{group_id}/meetings/")
def schedule_meeting(group_id: int, topic: str, meeting_datetime: datetime, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    meeting = Meeting(group_id=group_id, topic=topic, meeting_datetime=meeting_datetime)
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    
    return meeting

@app.post("/groups/{group_id}/contributions/")
def record_contribution(group_id: int, amount: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    contribution = Contribution(group_id=group_id, user_id=current_user.id, amount=amount)
    db.add(contribution)
    db.commit()
    db.refresh(contribution)
    
    return contribution

@app.get("/groups/{group_id}/members/")
def list_group_members(group_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    return members

@app.get("/groups/{group_id}/meetings/")
def list_meetings(group_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    meetings = db.query(Meeting).filter(Meeting.group_id == group_id).all()
    return meetings

@app.get("/groups/{group_id}/contributions/")
def list_contributions(group_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contributions = db.query(Contribution).filter(Contribution.group_id == group_id).all()
    return contributions

