import os
import logging
import sqlite3
import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get the bot token from environment variable
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DATABASE_PATH = "file_storage.db"
INITIAL_ADMIN_ID = int(os.environ.get("INITIAL_ADMIN_ID", "0"))  # Set your Telegram user ID as default admin

# Create a connection to the SQLite database
def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Initialize the database
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create files table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id TEXT NOT NULL,
        file_name TEXT NOT NULL,
        description TEXT,
        uploaded_by INTEGER NOT NULL,
        upload_date TEXT NOT NULL,
        mime_type TEXT,
        file_size INTEGER
    )
    ''')
    
    # Create tags table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL,
        tag TEXT NOT NULL,
        FOREIGN KEY (file_id) REFERENCES files (id) ON DELETE CASCADE
    )
    ''')
    
    # Create admins table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        added_on TEXT NOT NULL
    )
    ''')
    
    # Create stats table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS stats (
        id INTEGER PRIMARY KEY,
        total_files INTEGER DEFAULT 0,
        total_downloads INTEGER DEFAULT 0,
        total_searches INTEGER DEFAULT 0,
        last_updated TEXT
    )
    ''')
    
    # Insert initial admin if not exists
    if INITIAL_ADMIN_ID != 0:
        cursor.execute('''
        INSERT OR IGNORE INTO admins (user_id, added_on)
        VALUES (?, ?)
        ''', (INITIAL_ADMIN_ID, datetime.datetime.now().isoformat()))
    
    # Initialize stats if not exists
    cursor.execute('''
    INSERT OR IGNORE INTO stats (id, total_files, total_downloads, total_searches, last_updated)
    VALUES (1, 0, 0, 0, ?)
    ''', (datetime.datetime.now().isoformat(),))
    
    conn.commit()
    conn.close()

# Check if user is admin
async def is_admin(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    admin = cursor.execute('SELECT * FROM admins WHERE user_id = ?', (user_id,)).fetchone()
    conn.close()
    return admin is not None

# Admin-only decorator
def admin_only(func):
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if await is_admin(user_id):
            return await func(update, context, *args, **kwargs)
        else:
            await update.message.reply_text("Sorry, this command is for admins only.")
            return None
    return wrapped

# Update stats
async def update_stats(stat_type):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if stat_type == "files":
        cursor.execute('UPDATE stats SET total_files = total_files + 1, last_updated = ? WHERE id = 1', 
                     (datetime.datetime.now().isoformat(),))
    elif stat_type == "downloads":
        cursor.execute('UPDATE stats SET total_downloads = total_downloads + 1, last_updated = ? WHERE id = 1',
                     (datetime.datetime.now().isoformat(),))
    elif stat_type == "searches":
        cursor.execute('UPDATE stats SET total_searches = total_searches + 1, last_updated = ? WHERE id = 1',
                     (datetime.datetime.now().isoformat(),))
    
    conn.commit()
    conn.close()

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    commands = (
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
        "ⓘ /info <file_id> - Get file information\n"
    )
    
    await update.message.reply_text(
        f"Welcome to the File Sharing Bot!\n\n"
        f"Admin Commands:\n{commands}\n\n"
        f"Note: All commands can only be used by admins."
    )

@admin_only
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads from admins."""
    file = None
    file_name = "unknown"
    mime_type = "unknown"
    file_size = 0
    
    # Check which type of file it is
    if update.message.document:
        file = update.message.document
        file_name = file.file_name
        mime_type = file.mime_type
        file_size = file.file_size
    elif update.message.photo:
        file = update.message.photo[-1]  # Get the largest photo
        file_name = f"photo_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        mime_type = "image/jpeg"
        file_size = file.file_size
    elif update.message.video:
        file = update.message.video
        file_name = file.file_name or f"video_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        mime_type = file.mime_type
        file_size = file.file_size
    elif update.message.audio:
        file = update.message.audio
        file_name = file.file_name or f"audio_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
        mime_type = file.mime_type
        file_size = file.file_size
    elif update.message.voice:
        file = update.message.voice
        file_name = f"voice_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.ogg"
        mime_type = file.mime_type
        file_size = file.file_size
    
    if file:
        # Save file info to database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO files (file_id, file_name, description, uploaded_by, upload_date, mime_type, file_size)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            file.file_id,
            file_name,
            update.message.caption or "No description",
            update.effective_user.id,
            datetime.datetime.now().isoformat(),
            mime_type,
            file_size
        ))
        file_db_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # Update stats
        await update_stats("files")
        
        # Notify uploader
        await update.message.reply_text(
            f"File uploaded successfully!\n"
            f"File ID: {file_db_id}\n"
            f"File Name: {file_name}\n"
            f"Size: {file_size / 1024 / 1024:.2f} MB"
        )
    else:
        await update.message.reply_text("No file detected. Please send a file to upload.")

@admin_only
async def search_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for files by keyword."""
    if not context.args:
        await update.message.reply_text("Please provide a search keyword.\nUsage: /search <keyword>")
        return
    
    keyword = ' '.join(context.args)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Search in file names, descriptions, and tags
    cursor.execute('''
    SELECT DISTINCT f.id, f.file_name, f.description, f.mime_type, f.file_size, f.upload_date 
    FROM files f
    LEFT JOIN tags t ON f.id = t.file_id
    WHERE f.file_name LIKE ? OR f.description LIKE ? OR t.tag LIKE ?
    LIMIT 10
    ''', (f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'))
    
    files = cursor.fetchall()
    conn.close()
    
    # Update stats
    await update_stats("searches")
    
    if not files:
        await update.message.reply_text(f"No files found matching '{keyword}'.")
        return
    
    result = f"🔍 Search results for '{keyword}':\n\n"
    for file in files:
        result += f"ID: {file['id']}\n"
        result += f"📄 {file['file_name']}\n"
        result += f"📝 {file['description'][:50]}...\n"
        result += f"📅 {file['upload_date'][:10]}\n"
        result += f"💾 {file['file_size'] / 1024 / 1024:.2f} MB\n\n"
    
    await update.message.reply_text(result)

@admin_only
async def get_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get bot statistics."""
    conn = get_db_connection()
    cursor = conn.cursor()
    stats = cursor.execute('SELECT * FROM stats WHERE id = 1').fetchone()
    
    # Count total admins
    total_admins = cursor.execute('SELECT COUNT(*) as count FROM admins').fetchone()['count']
    
    # Count total space used
    total_size = cursor.execute('SELECT SUM(file_size) as total FROM files').fetchone()['total'] or 0
    
    conn.close()
    
    await update.message.reply_text(
        f"📊 Bot Statistics 📊\n\n"
        f"Total Files: {stats['total_files']}\n"
        f"Total Downloads: {stats['total_downloads']}\n"
        f"Total Searches: {stats['total_searches']}\n"
        f"Total Admins: {total_admins}\n"
        f"Total Storage Used: {total_size / 1024 / 1024 / 1024:.2f} GB\n"
        f"Last Updated: {stats['last_updated'][:19]}"
    )

@admin_only
async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get a shareable link for a file."""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Please provide a valid file ID.\nUsage: /link <file_id>")
        return
    
    file_id = int(context.args[0])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    file = cursor.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    conn.close()
    
    if not file:
        await update.message.reply_text(f"File with ID {file_id} not found.")
        return
    
    # Create a shareable link
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=file_{file_id}"
    
    await update.message.reply_text(
        f"🔗 Shareable link for '{file['file_name']}':\n{link}"
    )

@admin_only
async def edit_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit file description."""
    if len(context.args) < 2:
        await update.message.reply_text("Please provide a file ID and new description.\nUsage: /editdesc <file_id> <description>")
        return
    
    file_id = context.args[0]
    if not file_id.isdigit():
        await update.message.reply_text("Please provide a valid numeric file ID.")
        return
    
    file_id = int(file_id)
    new_desc = ' '.join(context.args[1:])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE files SET description = ? WHERE id = ?', (new_desc, file_id))
    affected_rows = conn.total_changes
    conn.commit()
    conn.close()
    
    if affected_rows > 0:
        await update.message.reply_text(f"Description updated for file ID {file_id}.")
    else:
        await update.message.reply_text(f"File with ID {file_id} not found.")

@admin_only
async def edit_filename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit file name."""
    if len(context.args) < 2:
        await update.message.reply_text("Please provide a file ID and new name.\nUsage: /editname <file_id> <new_name>")
        return
    
    file_id = context.args[0]
    if not file_id.isdigit():
        await update.message.reply_text("Please provide a valid numeric file ID.")
        return
    
    file_id = int(file_id)
    new_name = ' '.join(context.args[1:])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE files SET file_name = ? WHERE id = ?', (new_name, file_id))
    affected_rows = conn.total_changes
    conn.commit()
    conn.close()
    
    if affected_rows > 0:
        await update.message.reply_text(f"File name updated for file ID {file_id}.")
    else:
        await update.message.reply_text(f"File with ID {file_id} not found.")

@admin_only
async def add_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add tag to a file."""
    if len(context.args) < 2:
        await update.message.reply_text("Please provide a file ID and tag.\nUsage: /addtag <file_id> <tag>")
        return
    
    file_id = context.args[0]
    if not file_id.isdigit():
        await update.message.reply_text("Please provide a valid numeric file ID.")
        return
    
    file_id = int(file_id)
    tag = ' '.join(context.args[1:])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if file exists
    file = cursor.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    if not file:
        conn.close()
        await update.message.reply_text(f"File with ID {file_id} not found.")
        return
    
    # Add tag
    cursor.execute('INSERT INTO tags (file_id, tag) VALUES (?, ?)', (file_id, tag))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"Tag '{tag}' added to file ID {file_id}.")

@admin_only
async def remove_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove tag from a file."""
    if len(context.args) < 2:
        await update.message.reply_text("Please provide a file ID and tag.\nUsage: /removetag <file_id> <tag>")
        return
    
    file_id = context.args[0]
    if not file_id.isdigit():
        await update.message.reply_text("Please provide a valid numeric file ID.")
        return
    
    file_id = int(file_id)
    tag = ' '.join(context.args[1:])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM tags WHERE file_id = ? AND tag = ?', (file_id, tag))
    affected_rows = conn.total_changes
    conn.commit()
    conn.close()
    
    if affected_rows > 0:
        await update.message.reply_text(f"Tag '{tag}' removed from file ID {file_id}.")
    else:
        await update.message.reply_text(f"Tag '{tag}' not found for file ID {file_id}.")

@admin_only
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a new admin."""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Please provide a valid user ID.\nUsage: /addadmin <user_id>")
        return
    
    new_admin_id = int(context.args[0])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO admins (user_id, added_on) VALUES (?, ?)', 
                     (new_admin_id, datetime.datetime.now().isoformat()))
        conn.commit()
        await update.message.reply_text(f"User {new_admin_id} added as admin.")
    except sqlite3.IntegrityError:
        await update.message.reply_text(f"User {new_admin_id} is already an admin.")
    finally:
        conn.close()

@admin_only
async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove an admin."""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Please provide a valid user ID.\nUsage: /removeadmin <user_id>")
        return
    
    admin_id = int(context.args[0])
    
    # Don't allow removing the initial admin
    if admin_id == INITIAL_ADMIN_ID:
        await update.message.reply_text("Cannot remove the initial admin.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM admins WHERE user_id = ?', (admin_id,))
    affected_rows = conn.total_changes
    conn.commit()
    conn.close()
    
    if affected_rows > 0:
        await update.message.reply_text(f"Admin {admin_id} has been removed.")
    else:
        await update.message.reply_text(f"User {admin_id} is not an admin.")

@admin_only
async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all admins."""
    conn = get_db_connection()
    cursor = conn.cursor()
    admins = cursor.execute('SELECT user_id, added_on FROM admins ORDER BY id').fetchall()
    conn.close()
    
    if not admins:
        await update.message.reply_text("No admins found.")
        return
    
    result = "👥 Admin List:\n\n"
    for admin in admins:
        result += f"👤 ID: {admin['user_id']}\n"
        result += f"📅 Added: {admin['added_on'][:10]}\n"
        result += "------------------------\n"
    
    await update.message.reply_text(result)

@admin_only
async def delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a file."""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Please provide a valid file ID.\nUsage: /deletefile <file_id>")
        return
    
    file_id = int(context.args[0])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # First get the file info for confirmation
    file = cursor.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    
    if not file:
        conn.close()
        await update.message.reply_text(f"File with ID {file_id} not found.")
        return
    
    # Delete the file
    cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
    # Tags will be deleted automatically due to ON DELETE CASCADE
    
    conn.commit()
    conn.close()
    
    await update.message.reply_text(
        f"File deleted successfully:\n"
        f"ID: {file_id}\n"
        f"Name: {file['file_name']}"
    )

@admin_only
async def get_file_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get file information."""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Please provide a valid file ID.\nUsage: /info <file_id>")
        return
    
    file_id = int(context.args[0])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get file info
    file = cursor.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    
    if not file:
        conn.close()
        await update.message.reply_text(f"File with ID {file_id} not found.")
        return
    
    # Get tags
    tags = cursor.execute('SELECT tag FROM tags WHERE file_id = ?', (file_id,)).fetchall()
    tag_list = [tag['tag'] for tag in tags]
    
    conn.close()
    
    # Send file info
    info_text = (
        f"ⓘ File Information\n\n"
        f"ID: {file['id']}\n"
        f"Name: {file['file_name']}\n"
        f"Description: {file['description']}\n"
        f"Size: {file['file_size'] / 1024 / 1024:.2f} MB\n"
        f"Type: {file['mime_type']}\n"
        f"Uploaded by: {file['uploaded_by']}\n"
        f"Upload date: {file['upload_date'][:19]}\n"
        f"Tags: {', '.join(tag_list) if tag_list else 'No tags'}"
    )
    
    # Create keyboard with download button
    keyboard = [
        [InlineKeyboardButton("Download File", callback_data=f"download_{file['file_id']}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(info_text, reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks."""
    query = update.callback_query
    await query.answer()
    
    # Parse callback data
    data = query.data
    
    if data.startswith("download_"):
        telegram_file_id = data.split("_")[1]
        
        # Update download stats
        await update_stats("downloads")
        
        try:
            # Send the file
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=telegram_file_id,
                caption="Here's your requested file."
            )
        except Exception as e:
            logger.error(f"Error sending file: {e}")
            await query.message.reply_text(f"Error sending file: {str(e)}")

def main():
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Initialize database
    init_db()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("search", search_files))
    application.add_handler(CommandHandler("stats", get_stats))
    application.add_handler(CommandHandler("link", get_link))
    application.add_handler(CommandHandler("editdesc", edit_description))
    application.add_handler(CommandHandler("editname", edit_filename))
    application.add_handler(CommandHandler("addtag", add_tag))
    application.add_handler(CommandHandler("removetag", remove_tag))
    application.add_handler(CommandHandler("addadmin", add_admin))
    application.add_handler(CommandHandler("removeadmin", remove_admin))
    application.add_handler(CommandHandler("listadmins", list_admins))
    application.add_handler(CommandHandler("deletefile", delete_file))
    application.add_handler(CommandHandler("info", get_file_info))
    
    # Add file handler for admins
    application.add_handler(MessageHandler(
        filters.ATTACHMENT & ~filters.COMMAND,
        handle_file
    ))
    
    # Add callback query handler for buttons
    application.add_handler(CallbackQueryHandler(button_callback))

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()
