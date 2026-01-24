from .db import Base
from datetime import date, datetime
from sqlalchemy import Column, String, Boolean, Date, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY
from sqlalchemy.orm import relationship
import uuid

class User(Base):
    __tablename__ = 'users'

    # Match actual database schema
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    name = Column(String(100), nullable=False)  # First name

    # Onboarding fields
    session_id = Column(String(255), unique=True, nullable=True)
    password = Column(String(255), nullable=True)
    birthday = Column(Date, nullable=True)
    gender = Column(String(50), nullable=True)
    sexuality = Column(String(50), nullable=True)
    ethnicity = Column(String(100), nullable=True)
    pronouns = Column(String(50), nullable=True)
    university = Column(String(200), nullable=True)
    college_major = Column(String(200), nullable=True)
    occupation = Column(String(200), nullable=True)
    city = Column(String(200), nullable=True)  # City they live in
    bio = Column(String(500), nullable=True)  # AI-generated Instagram-style bio
    follower_sentence = Column(String(500), nullable=True)  # AI-generated sentence about follower/following stats
    conversations = Column(JSONB, default=list)  # Array of conversation dicts
    prompt = Column(String, nullable=True)  # Store the dynamic prompt state for user
    device_token = Column(String(255), nullable=True)  # APNs device token for push notifications
    eras = Column(ARRAY(String), default=list)  # Array of era texts (history of eras)
    profile_image = Column(String(500), nullable=True)  # Cartoon avatar URL from S3
    is_private = Column(Boolean, default=False, nullable=False)  # Profile privacy setting (default: public)


class Follow(Base):
    __tablename__ = 'follows'

    # Primary key
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Foreign keys
    follower_id = Column(String(36), ForeignKey('users.id'), nullable=False)  # User who follows
    following_id = Column(String(36), ForeignKey('users.id'), nullable=False)  # User being followed

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)


class FollowRequest(Base):
    __tablename__ = 'follow_requests'

    # Primary key
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Foreign keys
    requester_id = Column(String(36), ForeignKey('users.id'), nullable=False)  # User requesting to follow
    requested_id = Column(String(36), ForeignKey('users.id'), nullable=False)  # User being requested

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)


class Notification(Base):
    __tablename__ = 'notifications'

    # Primary key
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Foreign key - user who receives this notification
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)

    # Foreign key - user who triggered this notification (the actor)
    # For follow requests: the requester
    # For follow accepts: the accepter
    # For posts: the poster
    actor_id = Column(String(36), ForeignKey('users.id'), nullable=True)

    # Content of the notification
    content = Column(String, nullable=False)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)


class Report(Base):
    __tablename__ = 'reports'

    # Primary key
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Foreign keys
    reported_user_id = Column(String(36), ForeignKey('users.id'), nullable=False)  # User being reported
    reporter_id = Column(String(36), ForeignKey('users.id'), nullable=False)  # User who reported

    # Report details
    content_type = Column(String, nullable=True)  # Type of content being reported (e.g., "outfit", "user", "comment")
    content_id = Column(String(36), nullable=True)  # ID of the content being reported
    reason = Column(String, nullable=False)  # Why the content is inappropriate

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)


class Block(Base):
    __tablename__ = 'blocks'

    # Primary key
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Foreign keys
    blocker_id = Column(String(36), ForeignKey('users.id'), nullable=False)  # User who is blocking
    blocked_id = Column(String(36), ForeignKey('users.id'), nullable=False)  # User being blocked

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)


class Outfit(Base):
    """Hardcoded fashion outfits - matching fashion-feed schema"""
    __tablename__ = 'outfits'

    # Primary key - SERIAL (auto-incrementing integer)
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Outfit fields (matching SQL schema)
    base_title = Column(String, nullable=False)  # e.g., "1999 celeb caught by paparazzi"
    image_url = Column(String, nullable=False)  # URL/S3 path to outfit image
    gender = Column(String(20), nullable=True)  # "women", "men", or "unisex"

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    products = relationship("OutfitProduct", back_populates="outfit", cascade="all, delete-orphan")


class OutfitProduct(Base):
    """Cached outfit products - computed via CV model, cached forever"""
    __tablename__ = 'outfit_products'

    # Primary key - SERIAL
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Foreign key
    outfit_id = Column(String(36), ForeignKey('outfits.id'), nullable=False)

    # Product details (denormalized for caching)
    product_name = Column(String, nullable=False)
    brand = Column(String, nullable=False)
    retailer = Column(String, nullable=True)
    price_display = Column(String, nullable=False)  # "$49.99" or "₹1,299"
    price_value_usd = Column(String, nullable=False)  # Normalized to USD as string
    product_image_url = Column(String, nullable=False)
    product_url = Column(String, nullable=True)
    rank = Column(String, nullable=False)  # Display order: 1, 2, 3...

    # Timestamp
    computed_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    outfit = relationship("Outfit", back_populates="products")


class UserProgress(Base):
    """Track where each user left off in viewing outfits"""
    __tablename__ = 'user_progress'

    # Primary key - user_id
    user_id = Column(String(36), ForeignKey('users.id'), primary_key=True)

    # Current position
    current_outfit_id = Column(String(36), ForeignKey('outfits.id'), nullable=False)

    # Timestamp
    last_viewed_at = Column(DateTime, default=datetime.utcnow)


class OutfitTryOnSignup(Base):
    """Track users who sign up for outfit try-on feature"""
    __tablename__ = 'outfit_tryon_signups'

    # Primary key
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Foreign key to users table
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False, unique=True)

    # Denormalized email for easy export
    email = Column(String(120), nullable=False)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)


class UserOutfit(Base):
    """Track which outfits each user has saved/bought"""
    __tablename__ = 'user_outfits'

    # Primary key
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Foreign keys
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    outfit_id = Column(String(36), ForeignKey('outfits.id'), nullable=False)

    # AI-generated caption personalized to user
    caption = Column(String(500), nullable=True)  # "the fit she wears when she walks into cornell as a billionaire"

    # Timestamp
    saved_at = Column(DateTime, default=datetime.utcnow)


class Brand(Base):
    """Fashion brands that can be recommended to users"""
    __tablename__ = 'brands'

    # Primary key
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Brand details
    name = Column(String(200), nullable=False, unique=True)  # e.g., "PRADA", "dolce gabbana"
    description = Column(String(500), nullable=True)  # Brand vibe/personality
    price_range = Column(String(50), nullable=True)  # "affordable", "mid-range", "luxury"
    style_tags = Column(ARRAY(String), default=list)  # ["minimalist", "streetwear", "luxury"]

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)


class UserBrand(Base):
    """Junction table: many-to-many relationship between users and brands"""
    __tablename__ = 'user_brands'

    # Primary key
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Foreign keys
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    brand_id = Column(String(36), ForeignKey('brands.id'), nullable=False)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)

