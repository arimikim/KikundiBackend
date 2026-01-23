from fastapi import FastAPI, Depends, HTTPException, Header, status
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime, Boolean, Float, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from datetime import datetime
from pydantic import BaseModel, Field, validator
from dotenv import load_dotenv
import os
import logging
import firebase_admin
from firebase_admin import credentials, auth

cred = credentials.Certificate("firebase-service-account.json")
firebase_admin.initialize_app(cred)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ===================== DATABASE MODELS =====================

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    firebase_uid = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    phone = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)

class GroupMember(Base):
    __tablename__ = "group_members"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey('groups.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    joined_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="unique_group_member"),)

class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey('groups.id', ondelete='CASCADE'), nullable=False)
    topic = Column(String, nullable=False)
    meeting_datetime = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Contribution(Base):
    __tablename__ = "contributions"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey('groups.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    amount = Column(Float, nullable=False)
    contribution_date = Column(DateTime, default=datetime.utcnow)

class Poll(Base):
    __tablename__ = "polls"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey('groups.id', ondelete='CASCADE'), nullable=False)
    question = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)

class PollVote(Base):
    __tablename__ = "poll_votes"
    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, ForeignKey("polls.id", ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete='CASCADE'), nullable=False)
    vote = Column(Boolean, nullable=False)
    voted_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("poll_id", "user_id", name="unique_poll_vote"),)

Base.metadata.create_all(bind=engine)

# ===================== PYDANTIC MODELS =====================

class UserCreate(BaseModel):
    firebase_uid: str = Field(..., min_length=1)
    full_name: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=1)

class UserResponse(BaseModel):
    id: int
    firebase_uid: str
    full_name: str
    phone: str
    created_at: datetime
    class Config:
        from_attributes = True

class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)

class GroupResponse(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime
    created_by: int
    class Config:
        from_attributes = True

class ContributionCreate(BaseModel):
    amount: float = Field(..., gt=0)
    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('Amount must be greater than 0')
        return round(v, 2)

class MeetingCreate(BaseModel):
    topic: str = Field(..., min_length=1)
    meeting_datetime: datetime

class PollCreate(BaseModel):
    group_id: int = Field(..., gt=0)
    question: str = Field(..., min_length=1)

class VoteCreate(BaseModel):
    vote: bool

class AddMemberRequest(BaseModel):
    user_id: int = Field(..., gt=0)

# ===================== APP INITIALIZATION =====================

app = FastAPI(
    title="Group Management API",
    description="API for managing groups, contributions, meetings, and polls",
    version="1.0.0"
)

# ===================== DEPENDENCIES =====================

def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()

def get_current_user(authorization: str = Header(...), db: Session = Depends(get_db)) -> User:
    try:
        token = authorization.replace("Bearer","").strip()
        decoded = auth.verify_id_token(token)
        firebase_uid =decoded["uid"]
        
        if not firebase_uid:
            raise HTTPException(status_code=401, detail="Invalid authorization header")
        user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found. Please register first.")
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")

def verify_group_membership(group_id: int, user_id: int, db: Session) -> bool:
    member = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == user_id
    ).first()
    return member is not None

def to_iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else str(dt)

# ===================== USER ENDPOINTS =====================

@app.post("/register/", response_model=UserResponse, status_code=201)
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    try:
        existing_user = db.query(User).filter(User.firebase_uid == user.firebase_uid).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="User already registered")
        new_user = User(firebase_uid=user.firebase_uid, full_name=user.full_name, phone=user.phone)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        logger.info(f"User registered: {new_user.id}")
        return new_user
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Phone number already registered")
    except Exception as e:
        db.rollback()
        logger.error(f"Error registering user: {e}")
        raise HTTPException(status_code=500, detail="Failed to register user")

@app.get("/get_current_user/", response_model=UserResponse)
def get_user_info(current_user: User = Depends(get_current_user)):
    return current_user

# ===================== GROUP ENDPOINTS =====================

@app.post("/groups/", response_model=GroupResponse, status_code=201)
def create_group(group: GroupCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        if db.query(Group).filter(Group.name == group.name).first():
            raise HTTPException(status_code=400, detail="Group name already exists")
        new_group = Group(name=group.name, description=group.description, created_by=current_user.id)
        db.add(new_group)
        db.commit()
        db.refresh(new_group)
        member = GroupMember(group_id=new_group.id, user_id=current_user.id)
        db.add(member)
        db.commit()
        logger.info(f"Group created: {new_group.id}")
        return new_group
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating group: {e}")
        raise HTTPException(status_code=500, detail="Failed to create group")

@app.get("/groups/")
def get_groups(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        # Fetch groups where the current user is a member
        user_groups = db.query(Group).join(GroupMember).filter(GroupMember.user_id == current_user.id).all()
        result = []

        for group in user_groups:
            # Fetch members with explicit join
            members_query = db.query(GroupMember, User)\
                .join(User, GroupMember.user_id == User.id)\
                .filter(GroupMember.group_id == group.id).all()
            
            member_list = [{
                "id": user.id,
                "name": user.full_name,
                "role": "admin" if user.id == group.created_by else "member",
                "joined_at": member.joined_at.isoformat() if member.joined_at else None
            } for member, user in members_query]

            # Fetch contributions with explicit join
            contributions_query = db.query(Contribution, User)\
                .join(User, Contribution.user_id == User.id)\
                .filter(Contribution.group_id == group.id).all()

            contributions_map = {}
            for contrib, user in contributions_query:
                contributions_map[user.full_name] = contributions_map.get(user.full_name, 0.0) + float(contrib.amount)

            # Fetch transactions with explicit join and ordering
            transactions_query = db.query(Contribution, User)\
                .join(User, Contribution.user_id == User.id)\
                .filter(Contribution.group_id == group.id)\
                .order_by(Contribution.contribution_date.desc()).all()

            transaction_list = [{
                "id": contrib.id,
                "user_name": user.full_name,
                "user_id": user.id,
                "amount": float(contrib.amount),
                "date": contrib.contribution_date.isoformat() if contrib.contribution_date else None,
                "type": "contribution"
            } for contrib, user in transactions_query]

            # Append group details to result
            result.append({
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "created_at": group.created_at.isoformat() if group.created_at else None,
                "created_by": group.created_by,
                "members": member_list,
                "contributions": contributions_map,
                "transactions": transaction_list
            })

        return result

    except Exception as e:
        logger.error(f"Error fetching groups: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch groups")

@app.delete("/groups/{group_id}/")
def delete_group(group_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        if group.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="Only the group creator can delete the group")
        db.delete(group)
        db.commit()
        logger.info(f"Group deleted: {group_id}")
        return {"message": "Group deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting group: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete group")

# ===================== MEMBER ENDPOINTS =====================

@app.post("/groups/{group_id}/members/", status_code=201)
def add_group_member(group_id: int, member_data: AddMemberRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        if not verify_group_membership(group_id, current_user.id, db):
            raise HTTPException(status_code=403, detail="You are not a member of this group")
        user_to_add = db.query(User).filter(User.id == member_data.user_id).first()
        if not user_to_add:
            raise HTTPException(status_code=404, detail="User not found")
        if db.query(GroupMember).filter(GroupMember.group_id == group_id, GroupMember.user_id == member_data.user_id).first():
            raise HTTPException(status_code=400, detail="User is already a member of this group")
        member = GroupMember(group_id=group_id, user_id=member_data.user_id)
        db.add(member)
        db.commit()
        db.refresh(member)
        logger.info(f"Member {member_data.user_id} added to group {group_id}")
        return {"id": member.id, "group_id": member.group_id, "user_id": member.user_id,
                "user_name": user_to_add.full_name, "joined_at": member.joined_at.isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error adding member: {e}")
        raise HTTPException(status_code=500, detail="Failed to add member")

@app.get("/groups/{group_id}/members/")
def list_group_members(group_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        if not verify_group_membership(group_id, current_user.id, db):
            raise HTTPException(status_code=403, detail="You are not a member of this group")
        members = db.query(GroupMember, User).join(User).filter(GroupMember.group_id == group_id).all()
        return [{"id": user.id, "name": user.full_name, "phone": user.phone,
                 "role": "admin" if user.id == group.created_by else "member",
                 "joined_at": member.joined_at.isoformat()} for member, user in members]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing members: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch members")

# ===================== CONTRIBUTION ENDPOINTS =====================

@app.post("/groups/{group_id}/contributions/", status_code=201)
def record_contribution(group_id: int, contribution: ContributionCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        if not db.query(Group).filter(Group.id == group_id).first():
            raise HTTPException(status_code=404, detail="Group not found")
        if not verify_group_membership(group_id, current_user.id, db):
            raise HTTPException(status_code=403, detail="You are not a member of this group")
        new_contribution = Contribution(group_id=group_id, user_id=current_user.id, amount=contribution.amount)
        db.add(new_contribution)
        db.commit()
        db.refresh(new_contribution)
        logger.info(f"Contribution recorded: {new_contribution.id}")
        return {"id": new_contribution.id, "group_id": new_contribution.group_id, "user_id": new_contribution.user_id,
                "user_name": current_user.full_name, "amount": float(new_contribution.amount),
                "contribution_date": new_contribution.contribution_date.isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error recording contribution: {e}")
        raise HTTPException(status_code=500, detail="Failed to record contribution")

# ===================== MEETING ENDPOINTS =====================

@app.post("/groups/{group_id}/meetings/", status_code=201)
def schedule_meeting(group_id: int, meeting: MeetingCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        if not db.query(Group).filter(Group.id == group_id).first():
            raise HTTPException(status_code=404, detail="Group not found")
        if not verify_group_membership(group_id, current_user.id, db):
            raise HTTPException(status_code=403, detail="You are not a member of this group")
        new_meeting = Meeting(group_id=group_id, topic=meeting.topic, meeting_datetime=meeting.meeting_datetime)
        db.add(new_meeting)
        db.commit()
        db.refresh(new_meeting)
        logger.info(f"Meeting scheduled: {new_meeting.id}")
        return {"id": new_meeting.id, "group_id": new_meeting.group_id, "topic": new_meeting.topic,
                "meeting_datetime": new_meeting.meeting_datetime.isoformat(), "created_at": new_meeting.created_at.isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error scheduling meeting: {e}")
        raise HTTPException(status_code=500, detail="Failed to schedule meeting")

# ===================== POLL ENDPOINTS =====================

@app.post("/polls/", status_code=201)
def create_poll(poll: PollCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        if not db.query(Group).filter(Group.id == poll.group_id).first():
            raise HTTPException(status_code=404, detail="Group not found")
        if not verify_group_membership(poll.group_id, current_user.id, db):
            raise HTTPException(status_code=403, detail="You are not a member of this group")
        new_poll = Poll(group_id=poll.group_id, question=poll.question, created_by=current_user.id)
        db.add(new_poll)
        db.commit()
        db.refresh(new_poll)
        return {"id": new_poll.id, "group_id": new_poll.group_id, "question": new_poll.question,
                "created_at": new_poll.created_at.isoformat(), "created_by": new_poll.created_by}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating poll: {e}")
        raise HTTPException(status_code=500, detail="Failed to create poll")

@app.post("/polls/{poll_id}/votes", status_code=201)
def vote_poll(poll_id: int, vote_data: VoteCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        poll = db.query(Poll).filter(Poll.id == poll_id).first()
        if not poll:
            raise HTTPException(status_code=404, detail="Poll not found")
        if db.query(PollVote).filter(PollVote.poll_id == poll_id, PollVote.user_id == current_user.id).first():
            raise HTTPException(status_code=400, detail="User has already voted")
        new_vote = PollVote(poll_id=poll_id, user_id=current_user.id, vote=vote_data.vote)
        db.add(new_vote)
        db.commit()
        db.refresh(new_vote)
        return {"id": new_vote.id, "poll_id": new_vote.poll_id, "user_id": new_vote.user_id,
                "vote": new_vote.vote, "voted_at": new_vote.voted_at.isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error voting: {e}")
        raise HTTPException(status_code=500, detail="Failed to vote")

@app.get("/polls/{poll_id}/results")
def get_poll_results(poll_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        poll = db.query(Poll).filter(Poll.id == poll_id).first()
        if not poll:
            raise HTTPException(status_code=404, detail="Poll not found")
        total = db.query(PollVote).filter(PollVote.poll_id == poll_id).count()
        yes = db.query(PollVote).filter(PollVote.poll_id == poll_id, PollVote.vote == True).count()
        no = db.query(PollVote).filter(PollVote.poll_id == poll_id, PollVote.vote == False).count()
        return {"poll_id": poll_id, "question": poll.question, "total_votes": total, "yes_votes": yes, "no_votes": no,
                "yes_percentage": (yes / total * 100) if total > 0 else 0, "no_percentage": (no / total * 100) if total > 0 else 0}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching poll results: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch poll results")

# ===================== SEARCH/UTILITY ENDPOINTS =====================

@app.get("/users/search")
def search_users(query: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        if len(query) < 2:
            raise HTTPException(status_code=400, detail="Query must be at least 2 characters")
        users = db.query(User).filter((User.full_name.ilike(f"%{query}%")) | (User.phone.ilike(f"%{query}%"))).limit(20).all()
        return [{"id": u.id, "full_name": u.full_name, "phone": u.phone} for u in users]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching users: {e}")
        raise HTTPException(status_code=500, detail="Failed to search users")

@app.get("/groups/{group_id}/available-users")
def get_available_users_for_group(group_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        if not db.query(Group).filter(Group.id == group_id).first():
            raise HTTPException(status_code=404, detail="Group not found")
        if not verify_group_membership(group_id, current_user.id, db):
            raise HTTPException(status_code=403, detail="You are not a member of this group")
        member_ids = [m[0] for m in db.query(GroupMember.user_id).filter(GroupMember.group_id == group_id).all()]
        available = db.query(User).filter(User.id.notin_(member_ids)).all()
        return [{"id": u.id, "full_name": u.full_name, "phone": u.phone} for u in available]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching available users: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch available users")

# ===================== TEST ENDPOINTS =====================

@app.get("/test/users/")
def test_users(db: Session = Depends(get_db)):
    return [{"id": u.id, "firebase_uid": u.firebase_uid, "full_name": u.full_name, "phone": u.phone, "created_at": to_iso(u.created_at)} for u in db.query(User).all()]

@app.get("/test/groups/")
def test_groups(db: Session = Depends(get_db)):
    return [{"id": g.id, "name": g.name, "description": g.description, "created_at": to_iso(g.created_at), "created_by": g.created_by} for g in db.query(Group).all()]

@app.delete("/test/clear/")
def clear_test_data(db: Session = Depends(get_db)):
    try:
        for model in [PollVote, Poll, Contribution, Meeting, GroupMember, Group, User]:
            db.query(model).delete()
        db.commit()
        return {"message": "All test data cleared"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error clearing data: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear test data")

@app.get("/")
def root():
    return {"message": "Group Management API", "version": "1.0.0", "docs": "/docs"}