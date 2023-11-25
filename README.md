# Video speedup

Simple windows based gui (could work on linux too - but haven't tested) thrown together to automate a simple pre-canned video editing process, where duplicate frames are cut and the video is sped up. This was built specifically for the sims 4 footage.

This works by splitting a given video file into many, doing the necessary processing and merging them all back together, then applying a speed modifier.

Splitting up the video into parts to avoid running out of memory.

We also mask part of the screen which we want to ignore when considering duplicate frames.


## Building the executable

```
pyinstaller --noconsole --onefile .\gui.py
```

Will save an exe to the dist directory.

## Running the executable


Log files stored in same directory as the executable

The output video will be placed in the same directory as the input file with "_processed" appended to the name.

Tested on mkv files, no idea if it'll handle mp4 files.