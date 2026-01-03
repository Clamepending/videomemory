"""Mock action tools for executing various actions like sending emails, controlling doors, etc."""

from typing import Optional


def send_email(to: str, subject: Optional[str] = None, content: str = "") -> dict:
    """Sends an email to the specified recipient.
    
    Args:
        to: The email address of the recipient.
        subject: Optional subject line for the email.
        content: The body content of the email.
    
    Returns:
        dict: A dictionary containing the status and details of the email send operation.
    """
    print(f"--- send_email(to={to}, subject={subject}, content={content}) was called ---")
    
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
    print(f"--- open_door(door_name={door_name}) was called ---")
    
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
    print(f"--- close_door(door_name={door_name}) was called ---")
    
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
    print(f"--- turn_on_light(light_name={light_name}) was called ---")
    
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
    print(f"--- turn_off_light(light_name={light_name}) was called ---")
    
    # Mock implementation
    return {
        "status": "success",
        "message": f"Light '{light_name}' turned off successfully",
        "light_name": light_name,
    }

