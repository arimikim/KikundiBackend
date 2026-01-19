from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy.orm import Session,declarative_base,sessionmaker
from sqlalchemy import create_engine, Column, Integer, String,ForeignKey,DateTime
from datetime import datetime, timedelta
from pydantic import BaseModel


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

class UserCreate(BaseModel):
    firebase_uid: str
    full_name: str
    phone: str

class GroupCreate(BaseModel):
    name: str
    description: str
    firebase_uid: str

app = FastAPI()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
 
 
def get_current_user(authorization: str = Header(...), db: Session = Depends(get_db)):
    firebase_uid = authorization.replace("Bearer ", "").strip()
    user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    return user        

@app.post("/register/")
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.firebase_uid == user.firebase_uid).first()
    if db_user:
        raise HTTPException(status_code=400, detail="User already registered")
    
    new_user = User(
        firebase_uid=user.firebase_uid,
        full_name=user.full_name,
        phone=user.phone
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.post("/groups/")
def create_group(group: GroupCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db_group = db.query(Group).filter(Group.name == group.name).first()
    user = db.query(User).filter(User.firebase_uid == group.firebase_uid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if db_group:
        raise HTTPException(status_code=400, detail="Group name already exists")    
    
    new_group = Group(
        name=group.name,
        description=group.description,
        created_by=current_user.id
    )

    db.add(new_group)
    db.commit()
    db.refresh(new_group)

    member = GroupMember(group_id=new_group.id, user_id=current_user.id)
    db.add(member)
    db.commit()
    db.refresh(member)

    return {
        "id": new_group.id,
        "name": new_group.name,
        "description": new_group.description,
        "created_at": new_group.created_at,
        "created_by": new_group.created_by
    }


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

@app.get("/groups/", response_model=list[GroupCreate])
def get_groups(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Only fetch groups where the user is a member
    groups = db.query(Group).all()
    return [
        {
            "id": g.id,
            "name": g.name,
            "description": g.description,
            "created_by": g.created_by
        } for g in groups
    ]






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

@app.get("/groups/")
def list_groups(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    groups = db.query(Group).all()
    return groups

@app.get("/test/users/")
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return users

@app.get("/test/groups/")
def list_all_groups(db: Session = Depends(get_db)):
    groups = db.query(Group).all()
    return groups

@app.get("/test/group_members/")
def list_all_group_members(db: Session = Depends(get_db)):
    members = db.query(GroupMember).all()
    return members


@app.get("/get_current_user/")
def get_current_user(current_user: User = Depends(get_current_user)):
    return current_user