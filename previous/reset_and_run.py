import os
import subprocess
import sys

# Define the path to your app's directory
app_directory = os.path.dirname(os.path.realpath(__file__))

# Define the path to the user data directory
data_directory = os.path.join(app_directory, "scheduled_data")


# Function to reset user data (delete user-specific files)
def reset_user_data():
    if os.path.exists(data_directory):
        # Remove all user-specific data files in the scheduled_data directory
        for file in os.listdir(data_directory):
            file_path = os.path.join(data_directory, file)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                elif os.path.isdir(file_path):
                    os.rmdir(
                        file_path
                    )  # You may use shutil.rmtree for directories with contents
            except Exception as e:
                print(f"Error deleting file {file}: {e}")

    else:
        print(f"{data_directory} does not exist.")


# Function to run the app
def run_app():
    try:
        # Run the app using Flask's built-in server
        subprocess.run([sys.executable, "app.py"])
    except Exception as e:
        print(f"Error running the app: {e}")


if __name__ == "__main__":
    # Reset the user data
    reset_user_data()

    # Restart the Flas
