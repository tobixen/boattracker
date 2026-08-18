from crop_raymarine_track_to_gap import split_header, parse_trkpt, split_to_point, find_gap
from point import Point

with open('test_raymarine.gpx', 'r') as f:
    raymarine_data = f.read()
gap = {
            "jump_from": [
                37.48008333333333,
                -9.15181,
                "2023-06-05T002655",
                2.2222222222222223,
                219.37
            ],
            "jump_to": [
                37.31782166666667,
                -9.224758333333334,
                "2023-06-05T025151",
                1.9444444444444444,
                119.73
            ],
            "jump_distance": 19131.954199421056,
            "jump_distance_nm": 10.330428833380699,
            "jump_vmg_knots": 4.276626471960731,
            "jump_time": "2:24:56",
            "jump_time_seconds": 8696.0
}

trkpt = """   <trkpt lon="18.78876878879964" lat="54.40937597879916">
    <extensions>
     <raymarine:TrackPointExtension>
      <raymarine:WaterDepth>16.68</raymarine:WaterDepth>
     </raymarine:TrackPointExtension>
    </extensions>
   </trkpt>
"""
    
def test_split_header():
    header,rest = split_header(raymarine_data)
    assert '<?xml' in header
    assert '</extensions>' in header
    assert 'trkpt' not in header
    assert rest.startswith('<trkpt')
    assert rest.strip().endswith('</gpx>')

def test_parse_trkpt():
    pos = parse_trkpt(trkpt)
    assert pos.distance_to(Point(54.409375978, 18.7887688))<5

def test_split_to_point():
    part1, part2 = split_to_point(raymarine_data, Point(37.2885183, -9.186238), acceptable_distance2=400)

def test_find_gap():
    gap_track = find_gap(raymarine_data, gap, acceptable_distance2=400)
    ## TODO ... assume something
    #import pdb; pdb.set_trace()
