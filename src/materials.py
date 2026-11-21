"""Material presets for the simplified thermal model.

t_low / t_high : window for the predicted *interlayer* surface temperature (deg C) at the
                 moment the next layer is laid on top.  Above t_high -> overheating risk
                 (sagging, curling, blobby small features). Below t_low -> cold layers
                 (weak layer bonding, warping/delamination - mainly ABS/ASA/PC/PA).
tau_still      : surface cooling time constant with part fan OFF (s).  Fan shortens it.
fan_cap        : the highest part-fan % the optimizer will ever command for this material.
cold_matters   : if False, "too cold" is reported as info only (PLA bonds fine when cool).
These numbers are engineering estimates, NOT calibrated measurements.
"""
MATERIALS = {
    'PLA':  dict(tg=60,  t_low=30,  t_high=70,  tau_still=20.0, fan_cap=100, cold_matters=False),
    'PETG': dict(tg=80,  t_low=45,  t_high=92,  tau_still=22.0, fan_cap=70,  cold_matters=False),
    'ABS':  dict(tg=105, t_low=72,  t_high=125, tau_still=26.0, fan_cap=40,  cold_matters=True),
    'ASA':  dict(tg=100, t_low=68,  t_high=120, tau_still=26.0, fan_cap=40,  cold_matters=True),
    'PC':   dict(tg=147, t_low=100, t_high=165, tau_still=26.0, fan_cap=30,  cold_matters=True),
    'PA':   dict(tg=70,  t_low=60,  t_high=120, tau_still=26.0, fan_cap=30,  cold_matters=True),
    'TPU':  dict(tg=-30, t_low=25,  t_high=65,  tau_still=20.0, fan_cap=100, cold_matters=False),
}
ALIASES = [('PLA', 'PLA'), ('PCTG', 'PETG'), ('PETG', 'PETG'), ('PET', 'PETG'), ('ABS', 'ABS'),
           ('ASA', 'ASA'), ('PC', 'PC'), ('PA', 'PA'), ('PPA', 'PA'), ('NYLON', 'PA'),
           ('TPU', 'TPU'), ('TPE', 'TPU'), ('HIPS', 'ABS'), ('PVA', 'PLA')]
K_FAN = 3.0          # tau = tau_still / (1 + K_FAN * fan_fraction)
BEAD_FRAC = 0.5      # fresh bead effective temp = env + BEAD_FRAC * (nozzle - env)
DEPOSIT_MIX = 0.6    # weight of fresh bead vs. substrate in the post-deposition temperature

def resolve(filament_type):
    ft = (filament_type or '').upper().strip().strip('"')
    for key, mat in ALIASES:
        if ft.startswith(key):
            return mat, False
    return 'PETG', True   # unknown -> conservative middle preset
