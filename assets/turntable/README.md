#### USD Turntable Presets And You

---
#### Turning tables

`usd-qtpy` supports the rendering of assets with a turntable preset.
This turntable preset is a USD file, that gets referenced along with a temporary
export of the scene itself.

By using a hierarchical structure that conforms to the standard, you too 
can make a preset that turns your tables the exact way you wish your tables
to be turned.

#### Getting started

The turntable preset system requires the hierarchy to be laid out like so:

```
/
│
└─ turntable (Xform, default prim)
     │
     ├─ scene (Xform)
     │    │
     |    ├─ lights (Xform) (Optional)
     │    │    └─ [all lights in scene]
     │    │
     │    ├─ camera (Camera pointing at your target)
     │    │
     │    └─ [some scene geometry] (Optional)
     │
     ├─ parent (Xform, usually holds rotation animation)
     │
     └─ bounds (Xform) (Optional)
          │
          └─ [some invisible geometry that fits the bounds of your camera]

```

You can look at an example of a complete compliant hierarchy,
in `turntable_preset.usda`.
It isn't required to have a usda file, usd and usdc are supported as well.

##### Things that matter:
- `turntable` needs to be the default primitive
- Some Usd Camera needs to be present in the hierarchy
- `parent` must exist
- At least 1 `camera` exists somewhere (the first found camera will be used)

##### Things that don't matter:
- `bounds` doesn't have to exist
- `scene/lights` doesn't have to exist
- `camera` can be named anything and can exist everywhere in the hierarchy.

#### Functionality in the turntable system:
##### Bounds:
There are times where you are unsure whether assets will fit in the camera view.
This worry can be entirely mitigated by including the bounds Xform, with some
geometry in it that fills the camera view.

If `bounds` is present, the turntable will automagically fit the geometry
uniformly so that it fits the bounds of the geometry contained in this Xform.

##### Scene lights:
Scene lights can be included with any name in any order. These will be turned
off for GL renders, because GL renders are lit by default. The introduction
of lights would make the renders overexposed.

Should you still want to have lights regardless of the renderer being used,
just include them them in `scene`.

##### Parent:
This is where the subject of the turntable will end up,
and it's usually an Xform that holds rotation frames.

The subject is placed at the centroid and lower bound in the middle of the scene
automatically, meaning that you can place `parent` pretty much wherever you want
in the scene, the subject will inherit its transforms.

##### Limits (for now):
- USD attributes `endTimeCode` and `startTimeCode` are not able to be read, 
I might attempt to parse the actual description of the USD scene in the future, 
but for now, manual entry of  start and end timecodes is needed.

##### Happy turntabling!