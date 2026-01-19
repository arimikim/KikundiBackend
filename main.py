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

@app.post("/register/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    """Register a new user"""
    try:
        # Check if user already exists
        existing_user = db.query(User).filter(
            User.firebase_uid == user.firebase_uid
        ).first()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User already registered"
            )
        
        # Create new user
        new_user = User(
            firebase_uid=user.firebase_uid,
            full_name=user.full_name,
            phone=user.phone
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        logger.info(f"User registered successfully: {new_user.id}")
        return new_user
        
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        logger.error(f"Integrity error during registration: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number already registered"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Error registering user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register user"
        )


@app.get("/get_current_user/", response_model=UserResponse)
def get_user_info(current_user: User = Depends(get_current_user)):
    """Get current authenticated user information"""
    return current_user


# ===================== GROUP ENDPOINTS =====================

@app.post("/groups/", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
def create_group(
    group: GroupCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new group"""
    try:
        # Check if group name already exists
        existing_group = db.query(Group).filter(Group.name == group.name).first()
        if existing_group:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Group name already exists"
            )
        
        # Create new group
        new_group = Group(
            name=group.name,
            description=group.description,
            created_by=current_user.id
        )
        
        db.add(new_group)
        db.commit()
        db.refresh(new_group)
        
        # Add creator as first member
        member = GroupMember(
            group_id=new_group.id,
            user_id=current_user.id
        )
        db.add(member)
        db.commit()
        
        logger.info(f"Group created successfully: {new_group.id}")
        return new_group
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating group: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create group"
        )


@app.get("/groups/")
def get_groups(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all groups where the current user is a member with complete data"""
    try:
        # Get groups where user is a member
        user_groups = db.query(Group).join(GroupMember).filter(
            GroupMember.user_id == current_user.id
        ).all()
        
        result = []
        
        for group in user_groups:
            # Get all members for this group
            members_query = db.query(GroupMember, User).join(User).filter(
                GroupMember.group_id == group.id
            ).all()
            
            member_list = []
            for member, user in members_query:
                member_list.append({
                    "id": user.id,
                    "name": user.full_name,
                    "role": "admin" if user.id == group.created_by else "member",
                    "joined_at": member.joined_at.isoformat()
                })
            
            # Get contributions for this group
            contributions_query = db.query(Contribution, User).join(User).filter(
                Contribution.group_id == group.id
            ).all()
            
            # Aggregate contributions by user
            contributions_map = {}
            for contrib, user in contributions_query:
                if user.full_name not in contributions_map:
                    contributions_map[user.full_name] = 0.0
                contributions_map[user.full_name] += float(contrib.amount)
            
            # Get transaction history
            transactions_query = db.query(Contribution, User).join(User).filter(
                Contribution.group_id == group.id
            ).order_by(Contribution.contribution_date.desc()).all()
            
            transaction_list = []
            for contrib, user in transactions_query:
                transaction_list.append({
                    "id": contrib.id,
                    "user_name": user.full_name,
                    "user_id": user.id,
                    "amount": float(contrib.amount),
                    "date": contrib.contribution_date.isoformat(),
                    "type": "contribution"
                })
            
            result.append({
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "created_at": group.created_at.isoformat(),
                "created_by": group.created_by,
                "members": member_list,
                "contributions": contributions_map,
                "transactions": transaction_list
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Error fetching groups: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch groups"
        )


@app.get("/groups/{group_id}")
def get_group_details(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get detailed information about a specific group"""
    try:
        # Check if group exists
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group not found"
            )
        
        # Check if user is a member
        if not verify_group_membership(group_id, current_user.id, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this group"
            )
        
        # Get members
        members_query = db.query(GroupMember, User).join(User).filter(
            GroupMember.group_id == group_id
        ).all()
        
        members = [{
            "id": user.id,
            "name": user.full_name,
            "role": "admin" if user.id == group.created_by else "member",
            "joined_at": member.joined_at.isoformat()
        } for member, user in members_query]
        
        # Get contributions
        contributions_query = db.query(Contribution, User).join(User).filter(
            Contribution.group_id == group_id
        ).all()
        
        contributions_map = {}
        for contrib, user in contributions_query:
            if user.full_name not in contributions_map:
                contributions_map[user.full_name] = 0.0
            contributions_map[user.full_name] += float(contrib.amount)
        
        return {
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "created_at": group.created_at.isoformat(),
            "created_by": group.created_by,
            "members": members,
            "contributions": contributions_map
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching group details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch group details"
        )


@app.delete("/groups/{group_id}/", status_code=status.HTTP_200_OK)
def delete_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a group (only creator can delete)"""
    try:
        group = db.query(Group).filter(Group.id == group_id).first()
        
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group not found"
            )
        
        # Only creator can delete
        if group.created_by != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the group creator can delete the group"
            )
        
        db.delete(group)
        db.commit()
        
        logger.info(f"Group deleted: {group_id}")
        return {"message": "Group deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting group: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete group"
        )


# ===================== GROUP MEMBER ENDPOINTS =====================

@app.post("/groups/{group_id}/members/", status_code=status.HTTP_201_CREATED)
def add_group_member(
    group_id: int,
    member_data: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a member to a group"""
    try:
        # Check if group exists
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group not found"
            )
        
        # Check if requesting user is a member
        if not verify_group_membership(group_id, current_user.id, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this group"
            )
        
        # Check if user to add exists
        user_to_add = db.query(User).filter(User.id == member_data.user_id).first()
        if not user_to_add:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Check if already a member
        existing_member = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == member_data.user_id
        ).first()
        
        if existing_member:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is already a member of this group"
            )
        
        # Add member
        member = GroupMember(
            group_id=group_id,
            user_id=member_data.user_id
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        
        logger.info(f"Member {member_data.user_id} added to group {group_id}")
        return {
            "id": member.id,
            "group_id": member.group_id,
            "user_id": member.user_id,
            "user_name": user_to_add.full_name,
            "joined_at": member.joined_at.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error adding group member: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add member"
        )


@app.get("/groups/{group_id}/members/")
def list_group_members(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all members of a group"""
    try:
        # Check if group exists
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group not found"
            )
        
        # Check if user is a member
        if not verify_group_membership(group_id, current_user.id, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this group"
            )
        
        members = db.query(GroupMember, User).join(User).filter(
            GroupMember.group_id == group_id
        ).all()
        
        return [{
            "id": user.id,
            "name": user.full_name,
            "phone": user.phone,
            "role": "admin" if user.id == group.created_by else "member",
            "joined_at": member.joined_at.isoformat()
        } for member, user in members]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing group members: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch members"
        )


@app.delete("/groups/{group_id}/members/{user_id}/", status_code=status.HTTP_200_OK)
def remove_member(
    group_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove a member from a group"""
    try:
        # Check if group exists
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group not found"
            )
        
        # Only group creator or the member themselves can remove
        if group.created_by != current_user.id and current_user.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to remove this member"
            )
        
        # Can't remove the creator
        if user_id == group.created_by:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the group creator"
            )
        
        member = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id
        ).first()
        
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found in this group"
            )
        
        db.delete(member)
        db.commit()
        
        logger.info(f"Member {user_id} removed from group {group_id}")
        return {"message": "Member removed successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error removing member: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove member"
        )


# ===================== CONTRIBUTION ENDPOINTS =====================

@app.post("/groups/{group_id}/contributions/", status_code=status.HTTP_201_CREATED)
def record_contribution(
    group_id: int,
    contribution: ContributionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Record a contribution to a group"""
    try:
        # Check if group exists
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group not found"
            )
        
        # Check if user is a member
        if not verify_group_membership(group_id, current_user.id, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this group"
            )
        
        # Create contribution
        new_contribution = Contribution(
            group_id=group_id,
            user_id=current_user.id,
            amount=contribution.amount
        )
        
        db.add(new_contribution)
        db.commit()
        db.refresh(new_contribution)
        
        logger.info(f"Contribution recorded: {new_contribution.id}")
        return {
            "id": new_contribution.id,
            "group_id": new_contribution.group_id,
            "user_id": new_contribution.user_id,
            "user_name": current_user.full_name,
            "amount": float(new_contribution.amount),
            "contribution_date": new_contribution.contribution_date.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error recording contribution: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record contribution"
        )


@app.get("/groups/{group_id}/contributions/")
def list_contributions(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all contributions for a group"""
    try:
        # Check if group exists
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group not found"
            )
        
        # Check if user is a member
        if not verify_group_membership(group_id, current_user.id, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this group"
            )
        
        contributions = db.query(Contribution, User).join(User).filter(
            Contribution.group_id == group_id
        ).order_by(Contribution.contribution_date.desc()).all()
        
        return [{
            "id": contrib.id,
            "user_id": user.id,
            "user_name": user.full_name,
            "amount": float(contrib.amount),
            "contribution_date": contrib.contribution_date.isoformat()
        } for contrib, user in contributions]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing contributions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch contributions"
        )


# ===================== MEETING ENDPOINTS =====================

@app.post("/groups/{group_id}/meetings/", status_code=status.HTTP_201_CREATED)
def schedule_meeting(
    group_id: int,
    meeting: MeetingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Schedule a meeting for a group"""
    try:
        # Check if group exists
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group not found"
            )
        
        # Check if user is a member
        if not verify_group_membership(group_id, current_user.id, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this group"
            )
        
        # Create meeting
        new_meeting = Meeting(
            group_id=group_id,
            topic=meeting.topic,
            meeting_datetime=meeting.meeting_datetime
        )
        
        db.add(new_meeting)
        db.commit()
        db.refresh(new_meeting)
        
        logger.info(f"Meeting scheduled: {new_meeting.id}")
        return {
            "id": new_meeting.id,
            "group_id": new_meeting.group_id,
            "topic": new_meeting.topic,
            "meeting_datetime": new_meeting.meeting_datetime.isoformat(),
            "created_at": new_meeting.created_at.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error scheduling meeting: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to schedule meeting"
        )


@app.get("/groups/{group_id}/meetings/")
def list_meetings(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all meetings for a group"""
    try:
        # Check if group exists
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group not found"
            )
        
        # Check if user is a member
        if not verify_group_membership(group_id, current_user.id, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this group"
            )
        
        meetings = db.query(Meeting).filter(
            Meeting.group_id == group_id
        ).order_by(Meeting.meeting_datetime.desc()).all()
        
        return [{
            "id": meeting.id,
            "group_id": meeting.group_id,
            "topic": meeting.topic,
            "meeting_datetime": meeting.meeting_datetime.isoformat(),
            "created_at": meeting.created_at.isoformat()
        } for meeting in meetings]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing meetings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch meetings"
        )


# =====================