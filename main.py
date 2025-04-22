import os
import logging
from datetime import datetime
from pymongo import MongoClient
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGODB_URI = os.environ.get("MONGODB_URI")
ADMIN_IDS = [int(admin.strip()) for admin in os.environ.get("ADMIN_IDS", "").split(",") if admin.strip()]

# MongoDB setup
client = MongoClient(MONGODB_URI)
db = client["file_sharing_bot"]
files_collection = db["files"]
stats_collection = db["stats"]

# Initialize stats if not exists
if stats_collection.count_documents({}) == 0:
    stats_collection.insert_one({
        "total_files": 0,
        "total_downloads": 0,
        "total_users": 0,
        "last_updated": datetime.now()
    })

# Helper functions
async def is_admin(update: Update) -> bool:
    """Check if the user is an admin"""
    user_id = update.effective_user.id
    admins_list = ADMIN_IDS + [admin_id for admin in db["admins"].find()]
    return user_id in admins_list

async def get_file_info(file_id: str) -> dict:
    """Get file information from database"""
    return files_collection.find_one({"file_id": file_id})

async def update_stats(field: str):
    """Update bot statistics"""
    stats_collection.update_one({}, {"$inc": {field: 1}, "$set": {"last_updated": datetime.now()}})

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message when the command /start is issued."""
    welcome_message = (
        "🤖 *Welcome to File Sharing Bot* 🤖\n\n"
        "This bot allows administrators to upload and manage files.\n\n"
        "Available commands:\n"
        "📤 Upload any file to store it\n"
        "🔍 /search <keyword> - Search for files\n"
        "📊 /stats - View bot statistics\n"
        "🔗 /link <file_id> - Get a shareable link\n"
        "📝 /editdesc <file_id> <description> - Edit file description\n"
        "✏️ /editname <file_id> <new_name> - Edit file name\n"
        "🏷️ /addtag <file_id> <tag> - Add tag to file\n"
        "🏷️ /removetag <file_id> <tag> - Remove tag from file\n"
        "👤 /addadmin <user_id> - Add new admin\n"
        "👤 /removeadmin <user_id> - Remove admin\n"
        "👥 /listadmins - List all admins\n"
        "🗑️ /deletefile <file_id> - Delete a file\n"
        "ⓘ /info <file_id> - Get file information"
    )
    await update.message.reply_text(welcome_message, parse_mode="Markdown")
    
    # Update user stats
    if not db["users"].find_one({"user_id": update.effective_user.id}):
        db["users"].insert_one({
            "user_id": update.effective_user.id,
            "username": update.effective_user.username,
            "first_name": update.effective_user.first_name,
            "last_name": update.effective_user.last_name,
            "joined_date": datetime.now()
        })
        await update_stats("total_users")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle file uploads"""
    if not await is_admin(update):
        await update.message.reply_text("⚠️ Only admins can upload files.")
        return
    
    file = None
    file_type = None
    
    if update.message.document:
        file = update.message.document
        file_type = "document"
    elif update.message.photo:
        file = update.message.photo[-1]  # Get the largest photo
        file_type = "photo"
    elif update.message.video:
        file = update.message.video
        file_type = "video"
    elif update.message.audio:
        file = update.message.audio
        file_type = "audio"
    
    if file:
        # Extract caption or default to file name
        caption = update.message.caption or ""
        file_name = file.file_name if hasattr(file, 'file_name') else f"{file_type}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Extract tags from caption if present
        tags = []
        if "#" in caption:
            words = caption.split()
            tags = [word.strip("#") for word in words if word.startswith("#")]
            
        # Store file in database
        file_data = {
            "file_id": file.file_id,
            "file_name": file_name,
            "file_type": file_type,
            "description": caption,
            "tags": tags,
            "uploaded_by": update.effective_user.id,
            "upload_date": datetime.now(),
            "download_count": 0
        }
        
        files_collection.insert_one(file_data)
        await update_stats("total_files")
        
        await update.message.reply_text(
            f"✅ File uploaded successfully!\n"
            f"File ID: `{file.file_id}`\n"
            f"Name: {file_name}\n"
            f"Type: {file_type}\n"
            f"Tags: {', '.join(tags) if tags else 'None'}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ No file detected. Please upload a file.")

async def search_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search files by keyword"""
    if not await is_admin(update):
        await update.message.reply_text("⚠️ Only admins can search files.")
        return
        
    if not context.args:
        await update.message.reply_text("❌ Please provide a search term: /search <keyword>")
        return
        
    keyword = " ".join(context.args).lower()
    
    # Search in file names, descriptions and tags
    query = {
        "$or": [
            {"file_name": {"$regex": keyword, "$options": "i"}},
            {"description": {"$regex": keyword, "$options": "i"}},
            {"tags": {"$in": [keyword]}}
        ]
    }
    
    results = list(files_collection.find(query).limit(10))
    
    if not results:
        await update.message.reply_text(f"❌ No files found matching '{keyword}'")
        return
        
    response = f"🔍 Found {len(results)} files matching '{keyword}':\n\n"
    
    for idx, file in enumerate(results, 1):
        response += (
            f"{idx}. *{file['file_name']}*\n"
            f"   ID: `{file['file_id']}`\n"
            f"   Type: {file['file_type']}\n"
            f"   Tags: {', '.join(file['tags']) if file['tags'] else 'None'}\n\n"
        )
    
    await update.message.reply_text(response, parse_mode="Markdown")

async def get_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display bot statistics"""
    if not await is_admin(update):
        await update.message.reply_text("⚠️ Only admins can view statistics.")
        return
        
    stats = stats_collection.find_one({})
    
    if not stats:
        await update.message.reply_text("❌ Statistics not available.")
        return
        
    response = (
        "📊 *Bot Statistics*\n\n"
        f"Total Files: {stats['total_files']}\n"
        f"Total Downloads: {stats['total_downloads']}\n"
        f"Total Users: {stats['total_users']}\n"
        f"Last Updated: {stats['last_updated'].strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    await update.message.reply_text(response, parse_mode="Markdown")

async def get_file_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate shareable link for a file"""
    if not await is_admin(update):
        await update.message.reply_text("⚠️ Only admins can generate file links.")
        return
        
    if not context.args:
        await update.message.reply_text("❌ Please provide a file ID: /link <file_id>")
        return
        
    file_id = context.args[0]
    file = await get_file_info(file_id)
    
    if not file:
        await update.message.reply_text(f"❌ No file found with ID: {file_id}")
        return
        
    # Create a shareable link
    bot_username = context.bot.username
    link = f"https://t.me/{bot_username}?start=file_{file_id}"
    
    await update.message.reply_text(
        f"🔗 *Shareable Link*\n\n"
        f"File: {file['file_name']}\n"
        f"Link: {link}",
        parse_mode="Markdown"
    )

async def edit_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Edit file description"""
    if not await is_admin(update):
        await update.message.reply_text("⚠️ Only admins can edit file descriptions.")
        return
        
    if len(context.args) < 2:
        await update.message.reply_text("❌ Please provide file ID and new description: /editdesc <file_id> <description>")
        return
        
    file_id = context.args[0]
    new_description = " ".join(context.args[1:])
    
    result = files_collection.update_one(
        {"file_id": file_id},
        {"$set": {"description": new_description}}
    )
    
    if result.modified_count > 0:
        await update.message.reply_text(f"✅ Description updated for file ID: {file_id}")
    else:
        await update.message.reply_text(f"❌ No file found with ID: {file_id}")

async def edit_filename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Edit file name"""
    if not await is_admin(update):
        await update.message.reply_text("⚠️ Only admins can edit file names.")
        return
        
    if len(context.args) < 2:
        await update.message.reply_text("❌ Please provide file ID and new name: /editname <file_id> <new_name>")
        return
        
    file_id = context.args[0]
    new_name = " ".join(context.args[1:])
    
    result = files_collection.update_one(
        {"file_id": file_id},
        {"$set": {"file_name": new_name}}
    )
    
    if result.modified_count > 0:
        await update.message.reply_text(f"✅ File name updated for file ID: {file_id}")
    else:
        await update.message.reply_text(f"❌ No file found with ID: {file_id}")

async def add_tag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add tag to a file"""
    if not await is_admin(update):
        await update.message.reply_text("⚠️ Only admins can add tags.")
        return
        
    if len(context.args) < 2:
        await update.message.reply_text("❌ Please provide file ID and tag: /addtag <file_id> <tag>")
        return
        
    file_id = context.args[0]
    tag = context.args[1].lower()
    
    result = files_collection.update_one(
        {"file_id": file_id},
        {"$addToSet": {"tags": tag}}
    )
    
    if result.modified_count > 0:
        await update.message.reply_text(f"✅ Tag '{tag}' added to file ID: {file_id}")
    else:
        file = await get_file_info(file_id)
        if file:
            if tag in file.get("tags", []):
                await update.message.reply_text(f"ℹ️ Tag '{tag}' already exists for this file.")
            else:
                await update.message.reply_text(f"❌ Failed to add tag. Please try again.")
        else:
            await update.message.reply_text(f"❌ No file found with ID: {file_id}")

async def remove_tag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove tag from a file"""
    if not await is_admin(update):
        await update.message.reply_text("⚠️ Only admins can remove tags.")
        return
        
    if len(context.args) < 2:
        await update.message.reply_text("❌ Please provide file ID and tag: /removetag <file_id> <tag>")
        return
        
    file_id = context.args[0]
    tag = context.args[1].lower()
    
    result = files_collection.update_one(
        {"file_id": file_id},
        {"$pull": {"tags": tag}}
    )
    
    if result.modified_count > 0:
        await update.message.reply_text(f"✅ Tag '{tag}' removed from file ID: {file_id}")
    else:
        file = await get_file_info(file_id)
        if file:
            if tag not in file.get("tags", []):
                await update.message.reply_text(f"ℹ️ Tag '{tag}' does not exist for this file.")
            else:
                await update.message.reply_text(f"❌ Failed to remove tag. Please try again.")
        else:
            await update.message.reply_text(f"❌ No file found with ID: {file_id}")

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a new admin"""
    if not await is_admin(update):
        await update.message.reply_text("⚠️ Only admins can add other admins.")
        return
        
    if not context.args:
        await update.message.reply_text("❌ Please provide a user ID: /addadmin <user_id>")
        return
        
    try:
        new_admin_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ User ID must be a number.")
        return
        
    # Check if user is already an admin
    if new_admin_id in ADMIN_IDS or db["admins"].find_one({"user_id": new_admin_id}):
        await update.message.reply_text("ℹ️ This user is already an admin.")
        return
        
    db["admins"].insert_one({"user_id": new_admin_id, "added_by": update.effective_user.id, "added_date": datetime.now()})
    await update.message.reply_text(f"✅ User {new_admin_id} added as admin.")

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove an admin"""
    if not await is_admin(update):
        await update.message.reply_text("⚠️ Only admins can remove other admins.")
        return
        
    if not context.args:
        await update.message.reply_text("❌ Please provide a user ID: /removeadmin <user_id>")
        return
        
    try:
        admin_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ User ID must be a number.")
        return
        
    # Check if user is in environment variables (can't be removed)
    if admin_id in ADMIN_IDS:
        await update.message.reply_text("❌ Cannot remove default admins set in environment variables.")
        return
        
    result = db["admins"].delete_one({"user_id": admin_id})
    
    if result.deleted_count > 0:
        await update.message.reply_text(f"✅ User {admin_id} removed from admins.")
    else:
        await update.message.reply_text(f"❌ User {admin_id} is not an admin.")

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all admins"""
    if not await is_admin(update):
        await update.message.reply_text("⚠️ Only admins can view admin list.")
        return
        
    response = "👥 *Admin List*\n\n"
    
    # Add default admins from environment variables
    for admin_id in ADMIN_IDS:
        response += f"• {admin_id} (Default)\n"
    
    # Add admins from database
    db_admins = list(db["admins"].find())
    for admin in db_admins:
        response += f"• {admin['user_id']} (Added on {admin['added_date'].strftime('%Y-%m-%d')})\n"
    
    if not ADMIN_IDS and not db_admins:
        response += "No admins found."
    
    await update.message.reply_text(response, parse_mode="Markdown")

async def delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a file"""
    if not await is_admin(update):
        await update.message.reply_text("⚠️ Only admins can delete files.")
        return
        
    if not context.args:
        await update.message.reply_text("❌ Please provide a file ID: /deletefile <file_id>")
        return
        
    file_id = context.args[0]
    file = await get_file_info(file_id)
    
    if not file:
        await update.message.reply_text(f"❌ No file found with ID: {file_id}")
        return
    
    # Create confirmation keyboard
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, delete", callback_data=f"delete_yes_{file_id}"),
            InlineKeyboardButton("❌ No, cancel", callback_data=f"delete_no_{file_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"⚠️ Are you sure you want to delete this file?\n\n"
        f"File: {file['file_name']}\n"
        f"Type: {file['file_type']}\n"
        f"ID: {file_id}",
        reply_markup=reply_markup
    )

async def file_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get file information"""
    if not await is_admin(update):
        await update.message.reply_text("⚠️ Only admins can view file information.")
        return
        
    if not context.args:
        await update.message.reply_text("❌ Please provide a file ID: /info <file_id>")
        return
        
    file_id = context.args[0]
    file = await get_file_info(file_id)
    
    if not file:
        await update.message.reply_text(f"❌ No file found with ID: {file_id}")
        return
        
    response = (
        "ⓘ *File Information*\n\n"
        f"Name: {file['file_name']}\n"
        f"Type: {file['file_type']}\n"
        f"ID: `{file_id}`\n"
        f"Description: {file['description'] or 'None'}\n"
        f"Tags: {', '.join(file['tags']) if file['tags'] else 'None'}\n"
        f"Uploaded by: {file['uploaded_by']}\n"
        f"Upload date: {file['upload_date'].strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Downloads: {file['download_count']}"
    )
    
    # Send message with file info and download button
    keyboard = [[InlineKeyboardButton("📥 Download File", callback_data=f"download_{file_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(response, parse_mode="Markdown", reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries from inline keyboards"""
    query = update.callback_query
    await query.answer()
    
    if not await is_admin(update):
        await query.edit_message_text("⚠️ Only admins can perform this action.")
        return
    
    data = query.data
    
    if data.startswith("delete_yes_"):
        file_id = data.replace("delete_yes_", "")
        file = await get_file_info(file_id)
        
        if file:
            files_collection.delete_one({"file_id": file_id})
            await query.edit_message_text(f"✅ File '{file['file_name']}' has been deleted.")
            stats_collection.update_one({}, {"$inc": {"total_files": -1}})
        else:
            await query.edit_message_text("❌ File not found or already deleted.")
            
    elif data.startswith("delete_no_"):
        file_id = data.replace("delete_no_", "")
        await query.edit_message_text("❌ File deletion cancelled.")
        
    elif data.startswith("download_"):
        file_id = data.replace("download_", "")
        file = await get_file_info(file_id)
        
        if file:
            # Update download count
            files_collection.update_one({"file_id": file_id}, {"$inc": {"download_count": 1}})
            await update_stats("total_downloads")
            
            # Send the file
            try:
                if file["file_type"] == "document":
                    await context.bot.send_document(
                        update.effective_chat.id,
                        file["file_id"],
                        caption=file["description"] or None
                    )
                elif file["file_type"] == "photo":
                    await context.bot.send_photo(
                        update.effective_chat.id,
                        file["file_id"],
                        caption=file["description"] or None
                    )
                elif file["file_type"] == "video":
                    await context.bot.send_video(
                        update.effective_chat.id,
                        file["file_id"],
                        caption=file["description"] or None
                    )
                elif file["file_type"] == "audio":
                    await context.bot.send_audio(
                        update.effective_chat.id,
                        file["file_id"],
                        caption=file["description"] or None
                    )
                
                await query.edit_message_text(f"✅ File '{file['file_name']}' sent successfully.")
            except Exception as e:
                logger.error(f"Error sending file: {e}")
                await query.edit_message_text(f"❌ Error sending file: {str(e)}")
        else:
            await query.edit_message_text("❌ File not found.")

def main() -> None:
    """Start the bot"""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("search", search_files))
    application.add_handler(CommandHandler("stats", get_stats))
    application.add_handler(CommandHandler("link", get_file_link))
    application.add_handler(CommandHandler("editdesc", edit_description))
    application.add_handler(CommandHandler("editname", edit_filename))
    application.add_handler(CommandHandler("addtag", add_tag))
    application.add_handler(CommandHandler("removetag", remove_tag))
    application.add_handler(CommandHandler("addadmin", add_admin))
    application.add_handler(CommandHandler("removeadmin", remove_admin))
    application.add_handler(CommandHandler("listadmins", list_admins))
    application.add_handler(CommandHandler("deletefile", delete_file))
    application.add_handler(CommandHandler("info", file_info))
    
    # Handle file uploads
    application.add_handler(MessageHandler(
        filters.PHOTO | filters.DOCUMENT | filters.VIDEO | filters.AUDIO, 
        handle_file
    ))
    
    # Handle callback queries
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Start the Bot
    application.run_polling()

if __name__ == "__main__":
    main()
