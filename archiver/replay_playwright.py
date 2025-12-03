import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


async def playback_har():
    # Request user input for the HAR file path
    har_path = input("Enter the absolute path to the HAR file: ").strip()
    har_file = Path(har_path)

    # Validate the HAR file path
    if not har_file.is_file():
        print(f"Error: The file '{har_path}' does not exist or is not a valid file.")
        return

    # Launch Playwright and play back the HAR file
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # Use the HAR file for routing
            await page.route_from_har(har_path, update=False)
            print(f"Playing back HAR file: {har_path}")

            # Navigate to the first request in the HAR file
            await page.goto("")  # Replace with a relevant URL if needed
            print("Playback completed successfully.")

            await page.wait_for_timeout(300000000)

        except Exception as e:
            print(f"Error during playback: {e}")

        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(playback_har())