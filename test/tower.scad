// base plate + thin tower (island heating) + overhang bridge
union(){
  cube([60,60,4]);
  translate([8,8,0]) cube([8,8,45]);          // thin spire -> short layer times
  translate([35,35,0]) cylinder(d=20,h=25,$fn=64);
  translate([30,5,0]) cube([4,10,15]); translate([50,5,0]) cube([4,10,15]);
  translate([30,5,15]) cube([24,10,3]);      // bridge
}
