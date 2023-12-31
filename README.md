# Video speedup gui

Simple windows based gui (could work on linux too - but haven't tested) thrown together to automate a simple pre-canned video editing process, where duplicate frames are cut and the video is sped up. This was built specifically for the sims 4 footage.

This works by splitting a given directory of video files into chunks, doing frame deduplication then merging them all back together, applying a speed modifier.

Splitting up the video into parts avoids running out of memory (there is likely a way to get around this natively in ffmpeg but I havent found it yet).

We also mask part of the screen which we want to ignore for better duplicate frame detection.


## Building the executable

Note - requires python 3.11
```
python -m venv .venv
# activate the venv for your platform
pip install pyinstaller
pyinstaller --noconsole --onefile gui.py
```

Will save an exe to the dist directory.

## Running the executable


Log files stored in same directory as the executable

The output video will be placed in the same directory as the input file called "processed.mkv" appended to the name.

You will require ffmpeg to be available in your path for this to work.

Currently only handles .mkv files.

a config.toml file can be placed in the same directory as the executable where you can set the following options:
* video_split_secs: how long the split videos should be (to combat out of memory issues)
* speed_multiplier: how much the output video should be sped up by