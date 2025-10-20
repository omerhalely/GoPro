import pykitti
import numpy as np
import pymap3d as pm


def unpack_params(dataset):
    lons = [i.packet.lon for i in dataset.oxts]
    lats = [i.packet.lat for i in dataset.oxts]
    alts = [i.packet.alt for i in dataset.oxts]
    num_sats = [i.packet.numsats for i in dataset.oxts]
    pitches = [i.packet.pitch for i in dataset.oxts]
    rolls = [i.packet.roll for i in dataset.oxts]
    yaws = [i.packet.yaw for i in dataset.oxts]
    times = dataset.timestamps
    accs = [i.packet.pos_accuracy for i in dataset.oxts]
    return lons, lats, alts, num_sats, accs, pitches, rolls, yaws, times

def Extarct_ENU_NED(lats, lons, alts):
    lat0 = lats[0]
    lon0 = lons[0]
    alt0 = alts[0]
    ENU_coords_array = pm.geodetic2enu(lats, lons, alts, lat0, lon0, alt0)

    NED_coords_array = pm.geodetic2ned(lats, lons, alts, lat0, lon0, alt0)

    return ENU_coords_array, NED_coords_array

def build_reference_trajectory(dataset : pykitti.raw):
    lons, lats, alts, num_sats, accs, pitches, rolls, yaws, times = unpack_params(dataset)
    ENU, NED = Extarct_ENU_NED(lats, lons, alts)
    return np.array(ENU, dtype=np.float32), np.array(NED, dtype=np.float32), times

