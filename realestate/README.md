# 🏠 AQARI - Real Estate Platform



A production-ready real estate marketplace with real-time chat, encrypted user data, and Dockerized deployment. Built with Django, WebSockets, and microservices architecture.

## ✨ Features

### 🔐 **Security First**
- **AES-256 Encrypted PII** - Custom Django field for sensitive user data (national ID, phone)
- **JWT Authentication** - Stateless tokens for APIs & WebSockets
- **Password History Tracking** - Prevents reuse of last 6 passwords
- **Secure File Uploads** - Protected media storage with path validation

### 💬 **Real-time Communication**
- **WebSocket Chat** with Django Channels & Redis Pub/Sub
- **Typing Indicators** & **Read Receipts** in real-time
- **Online Presence** - Multi-device aware status tracking
- **Monetized Chat System** - 50 points per chat session with 60-day expiry

### ⚡ **High Performance**
- **Solved N+1 Queries** with `select_related` & `prefetch_related`
- **Atomic Transactions** for financial operations (point deductions)
- **Background Processing** with Celery for email notifications
- **Optimized Database Queries** with annotations and subqueries

### 🐳 **Production Ready**
- **Multi-container Docker** setup with Docker Compose
- **Service Separation** - HTTP, WebSocket, Worker services
- **Modern Dependency Management** - Pipenv with locked dependencies
- **Comprehensive API Docs** with Swagger/OpenAPI

## 🏗️ System Architecture

```
┌─────────────────┐     HTTP/REST     ┌─────────────────┐
│   Flutter App   │──────────────────▶│   Django HTTP   │
│    (Frontend)   │                   │   (Port: 9999)  │
└─────────────────┘                   └─────────────────┘
         │                                    │
         │ WebSocket (Port: 9998)             │ Database
         ▼                                    ▼
┌─────────────────┐    Redis Pub/Sub   ┌─────────────────┐
│  Django ASGI    │◀──────────────────▶│     Redis       │
│  (Daphne)       │                    │  (Message Bus)  │
└─────────────────┘                    └─────────────────┘
         │                                    │
         │ Channel Layer                      │ Task Queue
         ▼                                    ▼
┌─────────────────┐                    ┌─────────────────┐
│   Real-time     │                    │   Celery        │
│     Chat        │                    │   Worker        │
└─────────────────┘                    └─────────────────┘
```

## 📦 Tech Stack

| Component | Technology |
|-----------|------------|
| **Backend Framework** | Django 4.x, Django REST Framework |
| **Real-time** | Django Channels, Redis Pub/Sub, WebSockets |
| **Background Tasks** | Celery, Redis (Broker) |
| **Authentication** | JWT (SimpleJWT), Djoser |
| **Database** | SQLite (Development) |
| **Containerization** | Docker, Docker Compose |
| **Package Management** | Pipenv (Pipfile/Pipfile.lock) |
| **API Documentation** | Swagger/OpenAPI (drf-yasg) |
| **Testing** | Postman, Django Test Framework |

## 📁 Project Structure

```
realestate-project/
└── realestate/                          # Main Django project
    ├── realestate/                      # Project settings
    │   ├── settings.py                  # Main configuration
    │   ├── asgi.py                      # ASGI with Channels setup
    │   ├── celery.py                    # Celery configuration
    │   └── urls.py                      # URL routing
    │
    ├── users/                           # User management
    │   ├── models.py                    # Custom User & Profile models
    │   ├── fields.py                    # EncryptedCharField (AES-256)
    │   ├── serializers.py               # User serializers
    │   └── authentication/              # Auth views & logic
    │
    ├── chat/                            # Real-time chat system
    │   ├── consumers.py                 # WebSocket consumers
    │   ├── models.py                    # Conversation & Message models
    │   ├── views.py                     # Chat API endpoints
    │   ├── tasks.py                     # Celery tasks (email notifications)
    │   └── routing.py                   # WebSocket URL routing
    │
    ├── properties/                      # Property management
    │   ├── models.py                    # Property, Rating, Favorite models
    │   ├── views.py                     # API views with optimization
    │   ├── serializers.py               # Property serializers
    │   └── filters.py                   # Advanced property filtering
    │
    ├── notifications/                   # Notification system
    │   ├── consumers.py                 # Notification WebSocket handlers
    │   └── routing.py                   # Notification WebSocket routes
    │
    ├── core/                            # Shared utilities
    │   ├── middleware/                  # Custom middleware
    │   └── serializers/                 # Base serializers
    │
    ├── templates/                       # Email templates
    │   ├── email/                       # Transactional emails
    │   └── notifications/               # Notification templates
    │
    ├── media/                           # Uploaded files
    │   ├── userphotoes/                 # User profile photos
    │   ├── propertiesphotos/            # Property images
    │   └── chat_uploads/                # Chat file attachments
    │
    └── Pipfile                          # Pipenv dependencies
```

## 🚀 Quick Start with Docker (Recommended)

### Prerequisites
- Docker & Docker Compose
- Git

### Installation (One Command)
```bash
# 1. Clone the repository
git clone https://github.com/lamaDayoub/django-realestate.git
cd realestate

# 2. Create environment file from example
cp .env.example .env
# Edit .env with your configuration

# 3. Start all services
docker-compose up -d
```

### Access Services
- **API Documentation**: http://localhost:9999/swagger/
- **Django Admin**: http://localhost:9999/admin
- **WebSocket Server**: ws://localhost:9998


## 🔧 Environment Configuration

Create a `.env` file in the project root:

```env
# === Django Settings ===
SECRET_KEY=your-django-secret-key-here
ENCRYPTION_KEY=base64-encoded-32-byte-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# === Email Settings ===
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=your-email@gmail.com
```

**⚠️ Security Note:** Never commit `.env` file to version control. Use `.env.example` for template.

## 🧪 Local Development Setup (Using Pipenv)

### Development Environment
```bash
# 1. Install Pipenv if not already installed
pip install --user pipenv

# 2. Clone and navigate to project
git clone https://github.com/lamaDayoub/django-realestate.git
cd realestate

# 3. Install dependencies using Pipenv
pipenv install --dev

# 4. Activate the virtual environment
pipenv shell

# 5. Setup environment variables
cp .env.example .env
# Edit .env with your values

# 6. Setup database
python manage.py migrate
python manage.py createsuperuser

# 7. Run services in separate terminals
# Terminal 1: Django HTTP server
python manage.py runserver 0.0.0.0:8000

# Terminal 2: WebSocket server
daphne -b 0.0.0.0 -p 8001 realestate.asgi:application

# Terminal 3: Celery worker
celery -A realestate worker -l info

# Terminal 4: Redis (or use Docker)
redis-server
```

### Useful Pipenv Commands
```bash
# Install all dependencies
pipenv install --dev

# Run command in virtualenv without activating
pipenv run python manage.py migrate

# Check security vulnerabilities
pipenv check

# Show dependency graph
pipenv graph

# Lock dependencies
pipenv lock
```

## 🐳 Docker Services

| Service | Container Port | Host Port | Description |
|---------|---------------|-----------|-------------|
| `django_http` | 8888 | 9999 | Django REST API (HTTP) |
| `django_websocket` | 8889 | 9998 | WebSocket server (Daphne) |
| `celery_worker` | - | - | Background task processor |
| `redis` | 6379 | 6379 | Message broker & cache |

### Docker Commands Cheatsheet
```bash
# Start all services in background
docker-compose up -d

# View logs
docker-compose logs -f
docker-compose logs -f django_http
docker-compose logs -f django_websocket

# Stop services
docker-compose down

# Rebuild images
docker-compose build --no-cache

# Execute commands in container
docker-compose exec django_http python manage.py migrate
docker-compose exec django_http python manage.py createsuperuser

# Check service status
docker-compose ps
```

## 📡 Some of API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/login/` | JWT token authentication |
| `POST` | `/api/auth/refresh/` | Refresh JWT token |


### Properties
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/properties/` | List/search properties with advanced filters |
| `GET` | `/api/properties/{id}/` | Get property details |
| `PUT` | `/api/properties/{id}/` | Update property (owner only) |
| `POST` | `/api/properties/{id}/rate/` | Rate a property (1-5 stars) |

### Chat System
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/chat/check-status/{property_id}/` | Check chat availability & cost |
| `POST` | `/api/chat/activate/` | Activate/Reactivate chat session (50 points) |
| `GET` | `/api/chat/conversations/` | List user's conversations with unread counts |
| `GET` | `/api/chat/conversations/{id}/messages/` | Get conversation messages |


### Real-time WebSocket
Connect to: `ws://localhost:9998/ws/chat/{conversation_id}/?token={jwt_token}`

**WebSocket Events:**
```json
// Send message
{
  "type": "chat_message",
  "content": "Hello!",
  "message_type": "text",  
  "file_url": "optional_media_url"
}

// Typing indicator
{
  "type": "typing",
  "is_typing": true
}

// Mark messages as read
{
  "type": "mark_as_read",
  "message_ids": [1, 2, 3]
}
```

## 🔐 Security Implementation Highlights

### 1. Encrypted Database Fields (AES-256-GCM)
```python
# users/fields.py
class EncryptedCharField(models.TextField):
    """Custom field for AES-256-GCM encrypted sensitive data"""
    
    def get_prep_value(self, value):
        # Encrypt with unique nonce for each encryption
        cipher = AES.new(self.key, AES.MODE_GCM)
        ciphertext, tag = cipher.encrypt_and_digest(value.encode())
        return base64.b64encode(json.dumps({
            'nonce': base64.b64encode(cipher.nonce).decode(),
            'ciphertext': base64.b64encode(ciphertext).decode(),
            'tag': base64.b64encode(tag).decode()
        }).encode()).decode()
```

### 2. WebSocket JWT Authentication Middleware
```python
# realestate/channels_middleware.py
class TokenAuthMiddleware:
    """Extracts and validates JWT tokens from WebSocket query strings"""
    
    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            query_string = scope['query_string'].decode()
            params = parse_qs(query_string)
            token = params.get('token', [None])[0]
            
            if token:
                scope['user'] = await get_user_from_token(token)
            else:
                scope['user'] = AnonymousUser()
        
        return await self.inner(scope, receive, send)
```

### 3. Atomic Transactions for Financial Safety
```python
# chat/views.py - Point deduction for chat activation
with transaction.atomic():
    user.refresh_from_db()  # Get latest data
    user.points = F('points') - CHAT_COST  # Atomic operation
    user.save(update_fields=['points'])
    
    # Create or update conversation with expiry
    conversation.expires_at = timezone.now() + timedelta(days=60)
    conversation.save()
```

## ⚡ Performance Optimizations

### Solved N+1 Query Problem
```python
# Optimized conversation list query
conversations = Conversation.objects.filter(
    Q(participant1=user) | Q(participant2=user)
).annotate(
    last_message_id=Subquery(
        Message.objects.filter(
            conversation=OuterRef('pk')
        ).order_by('-created_at').values('id')[:1]
    ),
    unread_count=Count(
        'messages',
        filter=Q(messages__is_read=False) & ~Q(messages__sender=user)
    )
).select_related('participant1__profile', 'participant2__profile')
```

### Efficient Property Filtering
```python
class PropertyListView(ListAPIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {'is_for_rent': ['exact'], 'active': ['exact']}
    search_fields = ['city', 'location_text']
    ordering_fields = ['price', 'area', 'number_of_rooms']
    
    def get_queryset(self):
        return Property.objects.filter(active=True).prefetch_related('images')
```

## 🧪 Testing

### API Testing with Postman
1. Import the provided Postman collection
2. Set environment variables:
   - `base_url`: http://localhost:9999
   - `token`: JWT token obtained from login
3. Test flow: Authentication → Properties → Chat → Real-time

### WebSocket Testing
```bash
# Install wscat
npm install -g wscat

# Connect to WebSocket
wscat -c "ws://localhost:9998/ws/chat/1/?token=YOUR_JWT_TOKEN"

# Send test message
> {"type": "chat_message", "content": "Test", "message_type": "text"}
```

## 🚀 Deployment Guide

### Production Checklist
- [ ] Set `DEBUG=False` in `.env`
- [ ] Configure `ALLOWED_HOSTS` with your domain
- [ ] Use PostgreSQL instead of SQLite
- [ ] Set up SSL certificates (HTTPS)
- [ ] Configure proper logging
- [ ] Set up monitoring and alerts
- [ ] Implement database backups

### Docker Production Configuration
Create `docker-compose.prod.yml`:
```yaml
version: '3.8'
services:
  django_http:
    environment:
      - DEBUG=False
      - ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
    command: gunicorn realestate.wsgi:application --bind 0.0.0.0:8888 --workers 4
  
  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=aqari_prod
      - POSTGRES_USER=aqari_user
      - POSTGRES_PASSWORD=strong_password_here
    volumes:
      - postgres_data:/var/lib/postgresql/data
```

## 🤝 Contributing

1. **Fork** the repository
2. **Create** feature branch: `git checkout -b feature/amazing-feature`
3. **Commit** changes: `git commit -m 'Add amazing feature'`
4. **Push** to branch: `git push origin feature/amazing-feature`
5. **Open** a Pull Request

### Development Guidelines
- Follow Django coding style
- Write tests for new features
- Update documentation accordingly
- Use meaningful commit messages
- Keep code modular and maintainable


## 👩‍💻 Author

**Lama Dayoub**  
- GitHub: [@Lama_Dayoub](https://github.com/lamaDayoub)
- LinkedIn: [Lama Dayoub](https://linkedin.com/in/lama-dayoub)
- Email: lama1e2dayoub@gmail.com

## 🙏 Acknowledgments

- **Django** team for the excellent web framework
- **Django Channels** team for WebSocket support
- **Celery** team for background task processing
- **Redis** for reliable message brokering
- **Docker** community for containerization tools



**⭐ If you find this project useful, please give it a star on GitHub!**

*Built with passion and attention to detail* 🚀