import os

from tqdm import tqdm


def format_bytes(data, max_display=50):
    """Format byte data for display, showing both hex and ASCII where possible"""
    if len(data) > max_display:
        hex_repr = data[:max_display].hex(' ')
        suffix = f"... ({len(data)} bytes total)"
    else:
        hex_repr = data.hex(' ')
        suffix = ""

    # Try to show ASCII representation for printable chars
    ascii_repr = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in data[:max_display])

    return f"{hex_repr} {suffix}\n       ASCII: {ascii_repr}"


def compare_video_files(file1_path, file2_path, chunk_size=1024 * 1024, output_file=None, context_bytes=100):
    """
    Compare two video files to identify the first difference, which likely indicates
    where corruption begins.

    Args:
        file1_path: Path to the first video file
        file2_path: Path to the second video file
        chunk_size: Size of chunks to read (default: 1MB)
        output_file: Optional file to write the comparison results
        context_bytes: Bytes of context to display before/after corruption
    """
    file1_size = os.path.getsize(file1_path)
    file2_size = os.path.getsize(file2_path)

    processed_size = 0
    min_size = min(file1_size, file2_size)

    print(f"File 1: {file1_path} ({file1_size:,} bytes)")
    print(f"File 2: {file2_path} ({file2_size:,} bytes)")

    if file1_size != file2_size:
        print(f"WARNING: Files have different sizes! Size difference: {abs(file1_size - file2_size):,} bytes")

    with open(file1_path, 'rb') as f1, open(file2_path, 'rb') as f2:
        with tqdm(total=min_size, unit='B', unit_scale=True, desc="Comparing") as pbar:
            while processed_size < min_size:
                chunk1 = f1.read(chunk_size)
                chunk2 = f2.read(chunk_size)

                if not chunk1 or not chunk2:
                    break

                if chunk1 != chunk2:
                    # Find exact byte position of first difference
                    for i, (b1, b2) in enumerate(zip(chunk1, chunk2)):
                        if b1 != b2:
                            diff_position = processed_size + i

                            # Extract context around the corruption
                            f1.seek(max(0, diff_position - context_bytes))
                            before_context1 = f1.read(min(context_bytes, diff_position))
                            f1.seek(diff_position)
                            after_context1 = f1.read(context_bytes)

                            f2.seek(max(0, diff_position - context_bytes))
                            before_context2 = f2.read(min(context_bytes, diff_position))
                            f2.seek(diff_position)
                            after_context2 = f2.read(context_bytes)

                            print(f"\nFirst difference found at byte position: {diff_position:,}")

                            # Display context in a readable format
                            print("\nFile 1 context:")
                            print("BEFORE:", format_bytes(before_context1))
                            print("AFTER: ", format_bytes(after_context1))

                            print("\nFile 2 context:")
                            print("BEFORE:", format_bytes(before_context2))
                            print("AFTER: ", format_bytes(after_context2))

                            # Write to output file if requested
                            if output_file:
                                with open(output_file, 'w') as f:
                                    f.write(f"First corruption at byte: {diff_position:,}\n")
                                    f.write(f"File 1 before: {before_context1.hex()}\n")
                                    f.write(f"File 1 after: {after_context1.hex()}\n")
                                    f.write(f"File 2 before: {before_context2.hex()}\n")
                                    f.write(f"File 2 after: {after_context2.hex()}\n")

                            return diff_position

                processed_size += len(chunk1)
                pbar.update(len(chunk1))

    if file1_size != file2_size:
        print(f"\nNo differences found in common content. Files differ in length starting at byte {min_size:,}")
        return min_size
    else:
        print("\nFiles are identical")
        return None

if __name__ == "__main__":
    
    file1 = "C:/Users/yaniv/Documents/projects/InstagramArchiver/temp_video_segments/concatenated_video_0_real.mp4"
    file2 = "C:/Users/yaniv/Documents/projects/InstagramArchiver/temp_video_segments/concatenated_video_0.mp4"
    output_file = None
    
    compare_video_files(file1, file2, output_file=output_file)