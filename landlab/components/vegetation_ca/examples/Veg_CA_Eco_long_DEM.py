
# Authors: Sai Nudurupati & Erkan Istanbulluoglu, 15Feb15

# Import required libraries

import os
import numpy as np
from landlab.io import read_esri_ascii
from landlab import RasterModelGrid as rmg
from landlab.components.uniform_precip.generate_uniform_precip \
                        import PrecipitationDistribution
from landlab.components.radiation.radiation_field import Radiation
from landlab.components.PET.potential_evapotranspiration_field \
                        import PotentialEvapotranspiration
from landlab.components.soil_moisture.soil_moisture_multi_pft_new  \
                        import SoilMoisture
from landlab.components.single_vegetation.vegetation_multi_pft_new \
                        import Vegetation
from landlab.components.vegetation_ca.CA_Veg_new  import VegCA
import time

# GRASS = 0; SHRUB = 1; TREE = 2; BARE = 3;
# SHRUBSEEDLING = 4; TREESEEDLING = 5

## Function that converts text file to a dictionary
def txt_data_dict( InputFile ):
    f = open( InputFile )
    data1 = {}
    for line in f:
       if line.strip() != '' and line[0] != '#':
           m, n = line.split(':')
           line = f.next()
           e = line[:].strip()
           if e[0].isdigit():
               if e.find('.') != -1:
                   data1[m.strip()] = float(line[:].strip())
               else:
                   data1[m.strip()] = int(line[:].strip())
           else:
               data1[m.strip()] = line[:].strip()
    f.close()
    return data1.copy()

## Point to the input DEM
_DEFAULT_INPUT_FILE_1 = os.path.join(os.path.dirname(__file__),
                                 'DEM_10m.asc')
## Point to the input elevation file
_DEFAULT_INPUT_FILE_2 = os.path.join(os.path.dirname(__file__),
                                 'elevation_NS.npy')

InputFile = 'Inputs_Vegetation_CA_orig.txt'
data = txt_data_dict( InputFile ) # Create dictionary that holds the inputs

USE_DEM = 1    # Make this 0 to use a custom grid
if USE_DEM == 1:
    ## Importing Grid and Elevations from DEM
    (grid,elevation) = read_esri_ascii(_DEFAULT_INPUT_FILE_1)
    grid['node']['Elevation'] = elevation
else:
    ## Use an open book like grid - custom grid
    grid = rmg(53,67,10.)
    elev = np.load(_DEFAULT_INPUT_FILE_2)
    grid['node']['Elevation'] = elev
grid['cell']['VegetationType'] = np.random.randint(0,6,grid.number_of_cells)
# Dummy grid for PET
grid1 = rmg(5,4,5)
grid1['node']['Elevation'] = 1700. * np.ones(grid1.number_of_nodes)
grid1['cell']['VegetationType'] = np.arange(0,6)
# Create radiation, soil moisture and Vegetation objects
PD_D = PrecipitationDistribution(mean_storm = data['mean_storm_dry'],  \
                    mean_interstorm = data['mean_interstorm_dry'],
                    mean_storm_depth = data['mean_storm_depth_dry'])
PD_W = PrecipitationDistribution(mean_storm = data['mean_storm_wet'],  \
                    mean_interstorm = data['mean_interstorm_wet'],
                    mean_storm_depth = data['mean_storm_depth_wet'])
Rad = Radiation( grid )
Rad_PET = Radiation( grid1 )
PET_Tree = PotentialEvapotranspiration( grid1, method = data['PET_method'], \
                    MeanTmaxF = data['MeanTmaxF_tree'],
                    DeltaD = data['DeltaD'] )
PET_Shrub = PotentialEvapotranspiration( grid1, method = data['PET_method'], \
                    MeanTmaxF = data['MeanTmaxF_shrub'],
                    DeltaD = data['DeltaD'] )
PET_Grass = PotentialEvapotranspiration( grid1, method = data['PET_method'], \
                    MeanTmaxF = data['MeanTmaxF_grass'],
                    DeltaD = data['DeltaD'] )
SM = SoilMoisture( grid, data )   # Soil Moisture object
VEG = Vegetation( grid, data )    # Vegetation object
vegca = VegCA( grid1, data )      # Cellular automaton object

##########
n = data['n_long_DEM']   # Defining number of storms the model will be run
##########

## Create arrays to store modeled data
P = np.empty(n)    # Record precipitation
Tb = np.empty(n)    # Record inter storm duration
Tr = np.empty(n)    # Record storm duration
Time = np.empty(n) # To record time elapsed from the start of simulation

CumWaterStress = np.empty([n/55, grid.number_of_cells]) # Cum Water Stress
VegType = np.empty([n/55, grid.number_of_cells],dtype=int)

PET_ = np.zeros([365,grid1.number_of_cells])
Rad_Factor = np.empty([365,grid.number_of_cells])
EP30 = np.empty([365, grid1.number_of_cells]) # 30 day average PET to determine season
PET_threshold = 0  # Initializing PET_threshold to ETThresholddown

## Initializing inputs for Soil Moisture object
grid['cell']['LiveLeafAreaIndex'] = 1.6 * np.ones( grid.number_of_cells )
SM._SO = 0.59 * np.ones(grid.number_of_cells) # Initializing Soil Moisture
Tg = 365.    # Growing season in days


## Calculate current time in years such that Julian time can be calculated
current_time = 0                   # Start from first day of June

for i in range(0,365):
    Rad_PET.update( float(i)/365.25)
    PET_Tree.update( float(i)/365.25 )
    PET_Shrub.update( float(i)/365.25 )
    PET_Grass.update( float(i)/365.25 )
    PET_[i] = [PET_Grass._PET_value, PET_Shrub._PET_value, PET_Tree._PET_value,
                0., PET_Shrub._PET_value, PET_Tree._PET_value]
    Rad.update( float(i)/365.25 )
    Rad_Factor[i] = grid['cell']['RadiationFactor']
    if i < 30:
        if i == 0:
            EP30[0] = PET_[0]
        else:
            EP30[i] = np.mean(PET_[:i],axis = 0)
    else:
        EP30[i] = np.mean(PET_[i-30:i], axis = 0)


time_check = 0.               # Buffer to store current_time at previous storm
i_check = 0                   #
yrs = 0
Start_time = time.clock()     # Recording time taken for simulation
WS = 0.

## Run Time Loop
for i in range(0, n):
    # Update objects
    Julian = np.floor( (current_time - np.floor( current_time )) * 365.)
    if Julian < 182 or Julian > 273:  # Dry Season
        PD_D.update()
        P[i] = PD_D.storm_depth
        Tr[i] = PD_D.storm_duration
        Tb[i] = PD_D.interstorm_duration
    else:                             # Wet Season - Jul to Sep - NA Monsoon
        PD_W.update()
        P[i] = PD_W.storm_depth
        Tr[i] = PD_W.storm_duration
        Tb[i] = PD_W.interstorm_duration

    grid['cell']['PotentialEvapotranspiration'] =  \
            (np.choose(grid['cell']['VegetationType'],PET_[Julian])) * \
                        Rad_Factor[Julian]
    current_time = SM.update( current_time, P = P[i], Tr = Tr[i], Tb = Tb[i] )
    if Julian != 364:
        if EP30[Julian + 1,0] > EP30[Julian,0]:
            PET_threshold = 1  # 1 corresponds to ETThresholdup
        else:
            PET_threshold = 0  # 0 corresponds to ETThresholddown
    VEG.update(PotentialEvapotranspirationThreshold = PET_threshold)

    WS += (grid['cell']['WaterStress'])*Tb[i]/24.
    Time[i] = current_time

    # Cellular Automata
    if (current_time - time_check) >= 1.:
        VegType[yrs] = grid['cell']['VegetationType']
        CumWaterStress[yrs] = WS/Tg
        grid['cell']['CumulativeWaterStress'] = CumWaterStress[yrs]
        vegca.update()
        SM.initialize(  data, VEGTYPE = grid['cell']['VegetationType'])
        VEG.initialize( data, VEGTYPE = grid['cell']['VegetationType'] )
        time_check = current_time
        WS = 0
        i_check = i
        yrs += 1


Final_time = time.clock()

VegType[yrs] = grid['cell']['VegetationType']
Time_Consumed = (Final_time - Start_time)/60.    # in minutes

## Saving
sim = 'long_DEM_'
np.save(sim+'Tb',Tb)
np.save(sim+'Tr',Tr)
np.save(sim+'P',P)
np.save(sim+'VegType',VegType)
np.save(sim+'CumWaterStress', CumWaterStress)
np.save(sim+'Years',yrs)
np.save(sim+'Time_Consumed_minutes', Time_Consumed)
np.save(sim+'CurrentTime',Time)