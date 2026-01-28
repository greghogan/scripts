#!/usr/bin/env python

import sys
import glob

def merge_debate_files(debater_names, file_paths, output_filename="transcription.txt"):
    # The specific order of section titles
    titles = [
        "1AC", "1ACX", "1NC", "1NCX",
        "2AC", "2ACX", "2NC", "2NCX",
        "1NR", "1AR", "2NR", "2AR"
    ]

    # Unpack debater names
    # Mapping assumes order: Aff 1, Aff 2, Neg 1, Neg 2
    aff1, aff2, neg1, neg2 = debater_names

    # Map titles to speaker names
    # Note: For Cross-Ex (CX), mapping to the speaker being examined (who just spoke)
    # 1ACX -> 1AC was just given by Aff1
    # 1NCX -> 1NC was just given by Neg1
    # 2ACX -> 2AC was just given by Aff2
    # 2NCX -> 2NC was just given by Neg2
    speaker_map = {
        "1AC":  aff1, "1ACX": neg2,
        "1NC":  neg1, "1NCX": aff1,
        "2AC":  aff2, "2ACX": neg1,
        "2NC":  neg2, "2NCX": aff2,
        "1NR":  neg1,
        "1AR":  aff1,
        "2NR":  neg2,
        "2AR":  aff2
    }

    # Check if we have exactly 12 files
    if len(file_paths) != 12:
        print(f"Error: Expected exactly 12 text files, but found {len(file_paths)}.")
        print(f"Files found: {file_paths}")
        sys.exit(1)

    # Sort the files by name to ensure consistent ordering
    sorted_files = sorted(file_paths)

    try:
        with open(output_filename, 'w', encoding='utf-8') as outfile:
            # Pair each title with the corresponding sorted file
            for title, filepath in zip(titles, sorted_files):
                speaker = speaker_map.get(title, "Unknown")

                # Write the Section Header
                outfile.write(f"{'-'*20}\n")
                outfile.write(f"{title} - {speaker}\n")
                outfile.write(f"{'-'*20}\n\n")

                # Read the content of the individual file and write it to the output
                try:
                    with open(filepath, 'r', encoding='utf-8') as infile:
                        content = infile.read()
                        outfile.write(content)
                        # Add a newline at the end of each section for spacing
                        outfile.write("\n\n")
                except FileNotFoundError:
                    print(f"Error: The file '{filepath}' was not found.")
                    sys.exit(1)
                except Exception as e:
                    print(f"Error reading '{filepath}': {e}")
                    sys.exit(1)

        print(f"Successfully created '{output_filename}' containing all 12 sections.")

    except IOError as e:
        print(f"Error writing to output file: {e}")

if __name__ == "__main__":
    # Check arguments
    if len(sys.argv) != 5:
        print("Usage: python team-policy-debate-combine-transcript.py <Aff1 Name> <Aff2 Name> <Neg1 Name> <Neg2 Name>")
        sys.exit(1)

    names = sys.argv[1:]

    # Find all .txt files in current directory
    # Exclude the output file if it exists to avoid infinite loops or counting errors if run multiple times
    all_txt_files = glob.glob("*.txt")
    input_files = [f for f in all_txt_files if f != "transcription.txt"]

    merge_debate_files(names, input_files)
