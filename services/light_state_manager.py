from utils.project import *

settings['log'] = True
settings['verbosity'] = True
settings['dev'] = False

nem_bulis_base = {'on': True, 'bri': 255, 'ct': 450}
bulis_base     = {'on': True, 'bri': 200}

overrides = {
    'tuzzaro_ajtonal': {},
    'keramia_elott': {},
    'golyairoda_elott': {},
    'ovi_elott':     {},
    'pult':          {'on': False},
    'lahma_elott':   {},
    'teakonyha':     {},
    'oktopusz':      {'on': False},
    'trafohaz':      {'on': False},
    'PK_elott':      {},
    'merce_elott':   {},
    'tuzzaro_es_merce_kozott': {}
}

bulis = datetime.now().hour >= 21 or datetime.now().hour < 8

success_names, failed_names = [], []

for lid, info in read_lights():
    name = info.raw['name']
    state = info.raw['state']

    try:
        target = copy.deepcopy(bulis_base if bulis else nem_bulis_base)

        if bulis:                        # vivid random colour
            target['xy'] = [round(random.random(), 4), round(random.random(), 4)]

        target.update(overrides.get(name, {}))

        for k, v in target.items():      # send once if any field differs
            if state.get(k) != v:
                set_light_state(lid, name, target)
                break

        success_names.append(name)       # log success for this light

    except ModuleException as e:
        failed_names.append(name)
        ServiceException(
            f"Module error while trying to set light state {name}",
            original_exception=e,
            severity=2
        )
    except Exception:
        failed_names.append(name)
        ServiceException(
            f"Module error while trying to set light state {name}",
            severity=2
        )

# single detailed log entry
log({'success': success_names, 'failure': failed_names})
report("Light states set.", verbose=True)