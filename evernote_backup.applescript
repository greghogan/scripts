set exportPath to path to downloads folder as text

with timeout of (30 * 60) seconds
	tell application "Evernote"
		repeat with evernotebook in every notebook of application "Evernote"
			set notebookName to the name of evernotebook
			log notebookName
			
			set matches to find notes "notebook:" & "\"" & notebookName & "\""
			set fileString to exportPath & "Backup:Evernote:" & notebookName & ".enex"
			
			export matches to fileString
			if (count of matches) > 0 then
				set filePath to POSIX path of fileString
				
				do shell script "/usr/bin/gzip -f " & quoted form of filePath
			end if
		end repeat
	end tell
end timeout
