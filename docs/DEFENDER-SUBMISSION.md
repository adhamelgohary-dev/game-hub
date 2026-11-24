# Submitting a False Positive to Microsoft Defender (Click-Only Guide)

If Windows Defender or SmartScreen ever flags a GameRewind installer or executable before code-signing reputation is fully established, you can clear it directly with Microsoft in under 2 minutes (no terminal commands needed):

1. Open your browser and go to Microsoft Security Intelligence's submission portal:
   https://www.microsoft.com/en-us/wdsi/filesubmission
2. Click **Submit a file as a software developer** (or **Home user** if you don't want to sign in with a Microsoft account).
3. Click **Choose file** and select the flagged `GameRewind-Setup-vX.Y.Z.exe` or `GameRewind.exe`.
4. Under **Select the Microsoft security product**, choose **Microsoft Defender Antivirus**.
5. Under **What do you believe this file is?**, choose **Incorrectly detected as malware/malicious**.
6. In the notes box, write: *"Open-source MIT-licensed Windows game library & notes app built with Python/PySide6. Source code: https://github.com/adhamelgohary-dev/game-rewind"*.
7. Click **Submit**.
8. Microsoft typically reviews and clears clean open-source submissions within 24–72 hours; once cleared, Windows Defender updates its definitions automatically worldwide.
