param([string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies @([System.Drawing.Bitmap].Assembly.Location,[System.Drawing.Rectangle].Assembly.Location) -TypeDefinition @'
using System;
using System.Drawing;
public static class ProfilePartBounds {
 public static Rectangle Find(Bitmap image,Rectangle cell) {
  int left=cell.Right,top=cell.Bottom,right=cell.Left,bottom=cell.Top;
  for(int y=cell.Top;y<cell.Bottom;y++)for(int x=cell.Left;x<cell.Right;x++){
   if(image.GetPixel(x,y).A<32)continue;
   left=Math.Min(left,x);top=Math.Min(top,y);right=Math.Max(right,x);bottom=Math.Max(bottom,y);
  }
  if(right<left||bottom<top)throw new InvalidOperationException("Empty character part");
  return Rectangle.FromLTRB(Math.Max(cell.Left,left-2),Math.Max(cell.Top,top-2),Math.Min(cell.Right,right+3),Math.Min(cell.Bottom,bottom+3));
 }
}
'@
$source=Join-Path $RepositoryRoot 'docs\design\personal-profile\rig-sources'
$destination=Join-Path $RepositoryRoot 'client\public\profile-avatars'
$names=@('body','head','upperL','lowerL','upperR','lowerR','eyes','reference')
$maximums=@(384,384,128,128,128,128,160,256)
$manifest=@()
foreach($character in @('comic','robot','rabbit')){
 $sheet=[System.Drawing.Bitmap]::FromFile((Join-Path $source ($character+'.png')))
 $directory=Join-Path $destination $character
 New-Item -ItemType Directory -Force -Path $directory | Out-Null
 try{
  for($index=0;$index -lt 8;$index++){
   $column=$index%4;$row=[Math]::Floor($index/4)
   $left=[int][Math]::Round($sheet.Width*$column/4)+5;$right=[int][Math]::Round($sheet.Width*($column+1)/4)-5
   $top=[int][Math]::Round($sheet.Height*$row/2)+5;$bottom=[int][Math]::Round($sheet.Height*($row+1)/2)-5
   $bounds=[ProfilePartBounds]::Find($sheet,[System.Drawing.Rectangle]::FromLTRB($left,$top,$right,$bottom))
   $scale=$maximums[$index]/[Math]::Max($bounds.Width,$bounds.Height)
   $width=[int][Math]::Round($bounds.Width*$scale);$height=[int][Math]::Round($bounds.Height*$scale)
   $part=[System.Drawing.Bitmap]::new($width,$height,[System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
   $graphics=[System.Drawing.Graphics]::FromImage($part)
   try{
    $graphics.CompositingMode=[System.Drawing.Drawing2D.CompositingMode]::SourceCopy
    $graphics.InterpolationMode=[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.PixelOffsetMode=[System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $graphics.DrawImage($sheet,[System.Drawing.Rectangle]::new(0,0,$width,$height),$bounds,[System.Drawing.GraphicsUnit]::Pixel)
    $file=Join-Path $directory ($names[$index]+'.png')
    $part.Save($file,[System.Drawing.Imaging.ImageFormat]::Png)
    $manifest += [pscustomobject]@{character=$character;part=$names[$index];source=@($bounds.X,$bounds.Y,$bounds.Width,$bounds.Height);width=$width;height=$height;sha256=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()}
   }finally{$graphics.Dispose();$part.Dispose()}
  }
 }finally{$sheet.Dispose()}
}
[System.IO.File]::WriteAllText((Join-Path $destination 'manifest.json'),($manifest|ConvertTo-Json -Depth 5),[System.Text.UTF8Encoding]::new($false))
Write-Output ('Prepared '+$manifest.Count+' character parts.')
