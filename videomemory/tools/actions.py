"""Mock action tools for executing various actions like sending emails, controlling doors, etc."""

from typing import Optional
import logging
import os
import requests

logger = logging.getLogger(__name__)


def send_email(to: str, subject: Optional[str] = None, content: str = "") -> dict:
    """Sends an email to the specified recipient.
    
    Args:
        to: The email address of the recipient.
        subject: Optional subject line for the email.
        content: The body content of the email.
    
    Returns:
        dict: A dictionary containing the status and details of the email send operation.
    """
    logger.info(f"send_email(to={to}, subject={subject}, content={content}) was called")
    
    # Mock implementation - in a real system, this would actually send an email
    return {
        "status": "success",
        "message": f"Email sent successfully to {to}",
        "to": to,
        "subject": subject or "(no subject)",
        "content": content,
    }


def open_door(door_name: str) -> dict:
    """Opens a specified door.
    
    Args:
        door_name: The name or identifier of the door to open (e.g., "front door", "garage door").
    
    Returns:
        dict: A dictionary containing the status and details of the door operation.
    """
    logger.info(f"open_door(door_name={door_name}) was called")
    
    # Mock implementation - in a real system, this would control actual door hardware
    return {
        "status": "success",
        "message": f"Door '{door_name}' opened successfully",
        "door_name": door_name,
    }


def close_door(door_name: str) -> dict:
    """Closes a specified door.
    
    Args:
        door_name: The name or identifier of the door to close (e.g., "front door", "garage door").
    
    Returns:
        dict: A dictionary containing the status and details of the door operation.
    """
    logger.info(f"close_door(door_name={door_name}) was called")
    
    # Mock implementation - in a real system, this would control actual door hardware
    return {
        "status": "success",
        "message": f"Door '{door_name}' closed successfully",
        "door_name": door_name,
    }


def turn_on_light(light_name: str) -> dict:
    """Turns on a specified light.
    
    Args:
        light_name: The name or identifier of the light to turn on.
    
    Returns:
        dict: A dictionary containing the status and details of the light operation.
    """
    logger.info(f"turn_on_light(light_name={light_name}) was called")
    
    # Mock implementation
    return {
        "status": "success",
        "message": f"Light '{light_name}' turned on successfully",
        "light_name": light_name,
    }


def turn_off_light(light_name: str) -> dict:
    """Turns off a specified light.
    
    Args:
        light_name: The name or identifier of the light to turn off.
    
    Returns:
        dict: A dictionary containing the status and details of the light operation.
    """
    logger.info(f"turn_off_light(light_name={light_name}) was called")
    
    # Mock implementation
    return {
        "status": "success",
        "message": f"Light '{light_name}' turned off successfully",
        "light_name": light_name,
    }

def print_to_user(message: str) -> dict:
    """Prints a message to the user.
    
    Args:
        message: The message to print to the user. This will be printed to the console.
    
    Returns:
        dict: A dictionary containing the status and details of the print operation.
    """
    logger.info(f"print_to_user(message={message}) was called")
    
    print("[System] ", message)
    return {"status": "success", "message": message}


def send_discord_notification(message: str, username: Optional[str] = None) -> dict:
    """Sends a notification message to Discord via webhook.
    
    Args:
        message: The message content to send to Discord.
        username: Optional username to override the webhook's default bot name.
    
    Returns:
        dict: A dictionary containing the status and details of the Discord notification operation.
    """
    logger.info(f"send_discord_notification(message={message}, username={username}) was called")
    
    WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    
    if not WEBHOOK_URL:
        error_msg = "DISCORD_WEBHOOK_URL environment variable is not set"
        logger.error(error_msg)
        return {
            "status": "error",
            "message": error_msg,
            "error": "Missing environment variable",
        }
    
    data = {
        "content": message,
    }
    
    if username:
        data["username"] = username
    
    try:
        result = requests.post(WEBHOOK_URL, json=data)
        
        # Check for success (Status 204 means it worked)
        if result.status_code == 204:
            logger.info("Discord notification sent successfully")
            return {
                "status": "success",
                "message": f"Discord notification sent successfully: {message}",
                "content": message,
            }
        else:
            error_msg = f"Failed to send Discord notification. Status code: {result.status_code}"
            logger.error(error_msg)
            return {
                "status": "error",
                "message": error_msg,
                "status_code": result.status_code,
            }
    except Exception as e:
        error_msg = f"Error sending Discord notification: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "status": "error",
            "message": error_msg,
            "error": str(e),
        }


def send_telegram_notification(message: str) -> dict:
    """Sends a notification message to Telegram via the Bot API.
    
    Args:
        message: The message content to send to Telegram.
    
    Returns:
        dict: A dictionary containing the status and details of the Telegram notification operation.
    """
    logger.info(f"send_telegram_notification(message={message}) was called")
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token:
        error_msg = "TELEGRAM_BOT_TOKEN environment variable is not set"
        logger.error(error_msg)
        return {
            "status": "error",
            "message": error_msg,
            "error": "Missing environment variable",
        }
    
    if not chat_id:
        error_msg = "TELEGRAM_CHAT_ID environment variable is not set"
        logger.error(error_msg)
        return {
            "status": "error",
            "message": error_msg,
            "error": "Missing environment variable",
        }
    
    try:
        result = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        
        data = result.json()
        if data.get("ok"):
            logger.info("Telegram notification sent successfully")
            return {
                "status": "success",
                "message": f"Telegram notification sent successfully: {message}",
                "content": message,
            }
        else:
            error_msg = f"Telegram API error: {data.get('description', 'Unknown error')}"
            logger.error(error_msg)
            return {
                "status": "error",
                "message": error_msg,
                "error_code": data.get("error_code"),
            }
    except Exception as e:
        error_msg = f"Error sending Telegram notification: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "status": "error",
            "message": error_msg,
            "error": str(e),
        }


def main():
    """Test all action tools."""
    print("=" * 60)
    print("Testing all actions...")
    print("=" * 60)
    
    results = []
    
    # Test send_email
    print("1. Testing send_email...")
    try:
        result = send_email(to="test@example.com", subject="Test Subject", content="Test email content")
        if result.get("status") == "success":
            results.append(("send_email", True, result.get("message", "Success")))
            print(f"✓ send_email: SUCCESS")
        else:
            results.append(("send_email", False, result.get("message", "Unknown error")))
            print(f"✗ send_email: FAILED")
    except Exception as e:
        results.append(("send_email", False, str(e)))
        print(f"✗ send_email: FAILED\n  Error: {e}")
    
    # Test send_discord_notification
    print("2. Testing send_discord_notification...")
    try:
        result = send_discord_notification(message="🧪 Test notification from actions.py", username="VideoMemory Bot")
        if result.get("status") == "success":
            results.append(("send_discord_notification", True, result.get("message", "Success")))
            print(f"✓ send_discord_notification: SUCCESS")
        else:
            results.append(("send_discord_notification", False, result.get("message", "Unknown error")))
            print(f"✗ send_discord_notification: FAILED")
    except Exception as e:
        results.append(("send_discord_notification", False, str(e)))
        print(f"✗ send_discord_notification: FAILED\n  Error: {e}")
    
    # Test open_door
    print("3. Testing open_door...")
    try:
        result = open_door(door_name="front door")
        if result.get("status") == "success":
            results.append(("open_door", True, result.get("message", "Success")))
            print(f"✓ open_door: SUCCESS")
        else:
            results.append(("open_door", False, result.get("message", "Unknown error")))
            print(f"✗ open_door: FAILED")
    except Exception as e:
        results.append(("open_door", False, str(e)))
        print(f"✗ open_door: FAILED\n  Error: {e}")
    
    # Test close_door
    print("4. Testing close_door...")
    try:
        result = close_door(door_name="front door")
        if result.get("status") == "success":
            results.append(("close_door", True, result.get("message", "Success")))
            print(f"✓ close_door: SUCCESS")
        else:
            results.append(("close_door", False, result.get("message", "Unknown error")))
            print(f"✗ close_door: FAILED")
    except Exception as e:
        results.append(("close_door", False, str(e)))
        print(f"✗ close_door: FAILED\n  Error: {e}")
    
    # Test turn_on_light
    print("5. Testing turn_on_light...")
    try:
        result = turn_on_light(light_name="living room")
        if result.get("status") == "success":
            results.append(("turn_on_light", True, result.get("message", "Success")))
            print(f"✓ turn_on_light: SUCCESS")
        else:
            results.append(("turn_on_light", False, result.get("message", "Unknown error")))
            print(f"✗ turn_on_light: FAILED")
    except Exception as e:
        results.append(("turn_on_light", False, str(e)))
        print(f"✗ turn_on_light: FAILED\n  Error: {e}")
    
    # Test turn_off_light
    print("6. Testing turn_off_light...")
    try:
        result = turn_off_light(light_name="living room")
        if result.get("status") == "success":
            results.append(("turn_off_light", True, result.get("message", "Success")))
            print(f"✓ turn_off_light: SUCCESS")
        else:
            results.append(("turn_off_light", False, result.get("message", "Unknown error")))
            print(f"✗ turn_off_light: FAILED")
    except Exception as e:
        results.append(("turn_off_light", False, str(e)))
        print(f"✗ turn_off_light: FAILED\n  Error: {e}")
    
    # Test print_to_user
    print("7. Testing print_to_user...")
    try:
        result = print_to_user(message="Test message")
        if result.get("status") == "success":
            results.append(("print_to_user", True, result.get("message", "Success")))
            print(f"✓ print_to_user: SUCCESS")
        else:
            results.append(("print_to_user", False, result.get("message", "Unknown error")))
            print(f"✗ print_to_user: FAILED")
    except Exception as e:
        results.append(("print_to_user", False, str(e)))
        print(f"✗ print_to_user: FAILED\n  Error: {e}")
    
    # Print summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    successful = [name for name, success, _ in results if success]
    failed = [(name, msg) for name, success, msg in results if not success]
    
    for name, success, msg in results:
        status = "✓" if success else "✗"
        print(f"{status} {name}: {'SUCCESS' if success else 'FAILED'}")
        if not success:
            print(f"  Error: {msg}")
    
    print("-" * 60)
    print(f"Total: {len(results)} actions")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    if successful:
        print(f"Successful actions: {', '.join(successful)}")
    if failed:
        print(f"Failed actions: {', '.join([name for name, _ in failed])}")
    print("=" * 60)


if __name__ == "__main__":
    main()