from fastapi import FastAPI, Depends, HTTPException, Header, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime, Boolean, Float, UniqueConstraint
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from datetime import datetime
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict
from dotenv import load_dotenv
import os
import logging

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
    
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="unique_group_member"),
    )


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

    __table_args__ = (
        UniqueConstraint("poll_id", "user_id", name="unique_poll_vote"),
    )


# Create all tables
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


class MemberResponse(BaseModel):
    id: int
    name: str
    role: str
    joined_at: str


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


def get_current_user(
    authorization: str = Header(..., description="Bearer token with Firebase UID"),
    db: Session = Depends(get_db)
) -> User:
    """Extract and validate user from authorization header"""
    try:
        firebase_uid = authorization.replace("Bearer ", "").strip()
        
        if not firebase_uid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header"
            )
        
        user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found. Please register first."
            )
        
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )


def verify_group_membership(group_id: int, user_id: int, db: Session) -> bool:
    """Check if user is a member of the group"""
    member = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == user_id
    ).first()
    return member is not None


# ===================== USER ENDPOINTS =====================

# ... (keep all the existing code from the previous artifact, just adding new endpoints at the end)

# ===================== POLL ENDPOINTS (keeping existing code) =====================

@app.post("/polls/", status_code=status.HTTP_201_CREATED)
def create_poll(
    poll: PollCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a poll"""
    try:
        group = db.query(Group).filter(Group.id == poll.group_id).first()
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group not found"
            )
        
        if not verify_group_membership(poll.group_id, current_user.id, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this group"
            )
        
        new_poll = Poll(
            group_id=poll.group_id,
            question=poll.question,
            created_by=current_user.id
        )
        db.add(new_poll)
        db.commit()
        db.refresh(new_poll)
        
        return {
            "id": new_poll.id,
            "group_id": new_poll.group_id,
            "question": new_poll.question,
            "created_at": new_poll.created_at.isoformat(),
            "created_by": new_poll.created_by
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating poll: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create poll"
        )


@app.post("/polls/{poll_id}/votes", status_code=status.HTTP_201_CREATED)
def vote_poll(
    poll_id: int,
    vote_data: VoteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Vote on a poll"""
    try:
        poll = db.query(Poll).filter(Poll.id == poll_id).first()
        if not poll:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Poll not found"
            )

        existing_vote = db.query(PollVote).filter(
            PollVote.poll_id == poll_id,
            PollVote.user_id == current_user.id
        ).first()

        if existing_vote:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User has already voted"
            )

        new_vote = PollVote(
            poll_id=poll_id,
            user_id=current_user.id,
            vote=vote_data.vote
        )
        db.add(new_vote)
        db.commit()
        db.refresh(new_vote)
        
        return {
            "id": new_vote.id,
            "poll_id": new_vote.poll_id,
            "user_id": new_vote.user_id,
            "vote": new_vote.vote,
            "voted_at": new_vote.voted_at.isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error voting on poll: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to vote on poll"
        )


@app.get("/polls/{poll_id}/results")
def get_poll_results(
    poll_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get poll results"""
    try:
        poll = db.query(Poll).filter(Poll.id == poll_id).first()
        if not poll:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Poll not found"
            )

        total_votes = db.query(PollVote).filter(PollVote.poll_id == poll_id).count()
        yes_votes = db.query(PollVote).filter(
            PollVote.poll_id == poll_id,
            PollVote.vote == True
        ).count()
        no_votes = db.query(PollVote).filter(
            PollVote.poll_id == poll_id,
            PollVote.vote == False
        ).count()

        return {
            "poll_id": poll_id,
            "question": poll.question,
            "total_votes": total_votes,
            "yes_votes": yes_votes,
            "no_votes": no_votes,
            "yes_percentage": (yes_votes / total_votes * 100) if total_votes > 0 else 0,
            "no_percentage": (no_votes / total_votes * 100) if total_votes > 0 else 0
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching poll results: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch poll results"
        )


# ===================== SEARCH/UTILITY ENDPOINTS =====================

@app.get("/users/search")
def search_users(
    query: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Search for users by name or phone"""
    try:
        if not query or len(query) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query must be at least 2 characters"
            )
        
        # Search by name or phone
        users = db.query(User).filter(
            (User.full_name.ilike(f"%{query}%")) | 
            (User.phone.ilike(f"%{query}%"))
        ).limit(20).all()
        
        return [{
            "id": user.id,
            "full_name": user.full_name,
            "phone": user.phone
        } for user in users]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to search users"
        )


@app.get("/groups/{group_id}/available-users")
def get_available_users_for_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get users who are not yet members of the group"""
    try:
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group not found"
            )
        
        if not verify_group_membership(group_id, current_user.id, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this group"
            )
        
        # Get all user IDs who are already members
        member_ids = db.query(GroupMember.user_id).filter(
            GroupMember.group_id == group_id
        ).all()
        member_ids = [m[0] for m in member_ids]
        
        # Get users who are not members
        available_users = db.query(User).filter(
            User.id.notin_(member_ids)
        ).all()
        
        return [{
            "id": user.id,
            "full_name": user.full_name,
            "phone": user.phone
        } for user in available_users]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching available users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch available users"
        )


# ===================== TEST ENDPOINTS =====================

def to_iso(dt):
    """Helper function to convert datetime to ISO string"""
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


@app.get("/test/users/")
def test_list_users(db: Session = Depends(get_db)):
    """Test endpoint - Get all users without authentication"""
    try:
        users = db.query(User).all()
        return [{
            "id": user.id,
            "firebase_uid": user.firebase_uid,
            "full_name": user.full_name,
            "phone": user.phone,
            "created_at": to_iso(user.created_at)
        } for user in users]
    except Exception as e:
        logger.error(f"Error in test users endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch users"
        )


@app.get("/test/groups/")
def test_list_groups(db: Session = Depends(get_db)):
    """Test endpoint - Get all groups without authentication"""
    try:
        groups = db.query(Group).all()
        return [{
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "created_at": to_iso(group.created_at),
            "created_by": group.created_by
        } for group in groups]
    except Exception as e:
        logger.error(f"Error in test groups endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch groups"
        )


@app.get("/test/group_members/")
def test_list_all_group_members(db: Session = Depends(get_db)):
    """Test endpoint - Get all group members without authentication"""
    try:
        members = db.query(GroupMember, User, Group).join(
            User, GroupMember.user_id == User.id
        ).join(
            Group, GroupMember.group_id == Group.id
        ).all()
        
        return [{
            "id": member.id,
            "group_id": member.group_id,
            "group_name": group.name,
            "user_id": user.id,
            "user_name": user.full_name,
            "joined_at": to_iso(member.joined_at)
        } for member, user, group in members]
    except Exception as e:
        logger.error(f"Error in test group members endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch group members"
        )


@app.delete("/test/clear/")
def clear_test_data(db: Session = Depends(get_db)):
    """Test endpoint - Clear all data (DANGEROUS - use only in development!)"""
    try:
        # Delete in correct order due to foreign keys
        db.query(PollVote).delete()
        db.query(Poll).delete()
        db.query(Contribution).delete()
        db.query(Meeting).delete()
        db.query(GroupMember).delete()
        db.query(Group).delete()
        db.query(User).delete()
        db.commit()
        
        return {"message": "All test data cleared successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error clearing test data: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear test data"
        )


@app.get("/")
def root():
    """Root endpoint"""
    return {
        "message": "Group Management API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc"
    }