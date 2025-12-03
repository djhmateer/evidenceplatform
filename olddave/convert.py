import os
import asyncio
from pathlib import Path
from har2warc.har2warc import har2warc


async def generate_warc(har_path:str):
    warc_path =  har_path.replace(".har", ".warc")
    har2warc(har_path, warc_path)
    print(f"WARC file generated at: {warc_path}")


if __name__ == "__main__":
    har_path_arg = input("Enter the path to the HAR file: ")

    asyncio.run(generate_warc(har_path_arg))