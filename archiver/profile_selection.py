import json
import sys
from pathlib import Path

import toga
from toga.style import Pack
from toga.style.pack import COLUMN

from archiver.profile_registration import Profile, register_instagram_account
from root_anchor import ROOT_DIR


def select_profile() -> Profile:
    print("Fetching available profiles...")
    available_profiles_path = Path(ROOT_DIR) / "profiles/map.json"
    if not available_profiles_path.exists():
        if input("No profiles found. Would you like to register a new profile? (yes/no): "):
            register_instagram_account()
            print("Please run the script again to select the new profile.")
        sys.exit(1)
    with open(available_profiles_path, "r") as m:
        profile_dicts: list[dict] = json.loads(m.read())
        profiles_map = [Profile(**profile) for profile in profile_dicts]
    print("Available profiles:")
    for idx, profile in enumerate(profiles_map):
        print(f"{idx} {profile.name} (Instagram username: {profile.insta_username})")
    print(f"+ new")
    profile_selection = input("Enter the profile name to use: ")
    profile_selection = profile_selection.strip()
    profile = None
    if profile_selection == "+" or profile_selection.lower() == "new":
        register_instagram_account()
        print("Please run the script again to select the new profile.")
        sys.exit(0)
    if profile_selection.isdigit():
        idx = int(profile_selection)
        if 0 <= idx < len(profiles_map):
            profile = profiles_map[idx]
        else:
            raise Exception("Invalid profile index selected.")
    else:
        for p in profiles_map:
            if p.name == profile_selection:
                profile = p
                break
    if profile is None:
        raise Exception("No matching profile found for the given name.")
    return profile

def select_profile_toga(app: toga.App):
    available_profiles_path = Path("../profiles/map.json")
    if not available_profiles_path.exists():
        dialog = toga.Window(title="No Profiles Found")
        dialog.content = toga.Box(children=[
            toga.Label("No profiles found."),
            toga.Button("Register New Profile", on_press=lambda w: register_instagram_account() or app.exit()),
            toga.Button("Exit", on_press=lambda w: app.exit())
        ])
        dialog.show()
        return

    with open(available_profiles_path, "r") as m:
        profile_dicts = json.loads(m.read())
        profiles_map = [Profile(**profile) for profile in profile_dicts]

    def on_select_profile(widget):
        selection = profile_combo.value
        if selection == "+ new":
            register_instagram_account()
            toga.Window(title="Profile Registered", content=toga.Label("Please restart to select the new profile.")).show()
            app.exit()
        else:
            for p in profiles_map:
                if p.name == selection:
                    app.selected_profile = p
                    app.main_window.dialog(toga.InfoDialog("Profile Selected", f"Selected profile: {p.name}"))
                    break

    profile_names = [p.name for p in profiles_map]
    profile_combo = toga.ComboBox(items=profile_names + ["+ new"])
    select_button = toga.Button("Select", on_press=on_select_profile)

    box = toga.Box(children=[
        toga.Label("Select a profile:"),
        profile_combo,
        select_button
    ], style=Pack(direction=COLUMN, margin=10))

    app.main_window.content = box
