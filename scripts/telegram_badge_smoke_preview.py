#!/usr/bin/env python3
"""Draw a one-off visual preview of TOP, VALUE and ACES badges. No tennis data."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def render(path: str):
    cards=[("TOP",(255,185,34),(190,92,0)),
           ("VALUE",(202,96,255),(94,10,170)),
           ("ACES",(34,224,239),(0,99,127))]
    picture=Image.new("RGB",(590,205),(31,35,44))
    d=ImageDraw.Draw(picture)
    font_path="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    for idx,(label,light,dark) in enumerate(cards):
        x=47+174*idx; y=29; w=h=132
        d.rounded_rectangle((x+3,y+4,x+w+3,y+h+4),radius=26,fill=(13,16,25))
        d.rounded_rectangle((x,y,x+w,y+h),radius=26,fill="white")
        d.rounded_rectangle((x+4,y+4,x+w-4,y+h-4),radius=23,fill=(12,16,22))
        for k in range(3):
            color=tuple(int(light[i]*(1-k/5)+dark[i]*k/5) for i in range(3))
            top=y+10+k*36
            d.rounded_rectangle((x+10,top,x+w-10,min(top+39,y+h-10)),radius=16,fill=color)
        d.rounded_rectangle((x+9,y+9,x+w-9,y+h-9),radius=21,outline=(242,248,252),width=3)
        size={"TOP":49,"VALUE":30,"ACES":39}[label]
        f=ImageFont.truetype(font_path,size)
        bb=d.textbbox((0,0),label,font=f,stroke_width=0)
        tw=bb[2]-bb[0];th=bb[3]-bb[1]
        cx=x+w//2-tw//2; cy=y+h//2-th//2-bb[1]
        d.text((cx+2,cy+3),label,font=f,fill=(28,22,33),stroke_width=3,stroke_fill=(18,20,29))
        d.text((cx,cy),label,font=f,fill="white",stroke_width=1,stroke_fill=(80,52,59))
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    picture.save(path,format="PNG",optimize=True)

if __name__=="__main__":
    import sys
    render(sys.argv[1] if len(sys.argv)>1 else "/tmp/blinq-telegram-badge-preview.png")
