import copy
import os
import random
import threading

from gasp import general
from gasp import population
from gasp.restart.restart import RestartFile


def creat_organisms(objects_dict, garun_dir, data_writer, log_writer, THIS_PATH,
                    whole_pop, num_finished_calcs, initial_population):
    organism_creators = objects_dict['organism_creators']
    num_calcs_at_once = objects_dict['num_calcs_at_once']
    ncalcs_to_restart = objects_dict['num_calcs_to_restartfile']
    composition_space = objects_dict['composition_space']
    constraints = objects_dict['constraints']
    geometry = objects_dict['geometry']
    developer = objects_dict['developer']
    redundancy_guard = objects_dict['redundancy_guard']
    stopping_criteria = objects_dict['stopping_criteria']
    energy_calculator = objects_dict['energy_calculator']
    pool = objects_dict['pool']
    id_generator = objects_dict['id_generator']

    threads = []
    relaxed_organisms = {}
    logstr_dicts = {}
    # populate the initial population
    for creator in organism_creators:
        logstr = f'Making {creator.number} organisms with {creator.name}'
        log_writer.write_data(logstr)

        while not creator.is_finished and not stopping_criteria.are_satisfied:
            # start initial batch of energy calculations
            if len(threads) < num_calcs_at_once:
                # make a new organism - keep trying until we get one
                new_organism = creator.create_organism(
                    id_generator, composition_space, constraints, log_writer, random)
                while new_organism is None and not creator.is_finished:
                    new_organism = creator.create_organism(
                        id_generator, composition_space, constraints, log_writer, random)
                if new_organism is not None:  # loop above could return None
                    geometry.unpad(new_organism.cell, constraints)
                    if developer.develop(new_organism, composition_space,
                                         constraints, geometry, pool, log_writer):
                        redundant_organism = redundancy_guard.check_redundancy(
                            new_organism, whole_pop, geometry, log_writer)
                        if redundant_organism is None:  # no redundancy
                            # add a copy to whole_pop so the organisms in
                            # whole_pop don't change upon relaxation
                            whole_pop.append(copy.deepcopy(new_organism))
                            geometry.pad(new_organism.cell)
                            stopping_criteria.update_calc_counter()
                            index = len(threads)
                            outstrs = {}
                            thread = threading.Thread(
                                target=energy_calculator.do_energy_calculation,
                                args=[new_organism, relaxed_organisms, logstr_dicts,
                                      index, composition_space])
                            thread.start()
                            threads.append(thread)

            # process finished calculations and start new ones
            else:
                for index, thread in enumerate(threads):
                    if not thread.is_alive():
                        num_finished_calcs += 1
                        relaxed_organism = relaxed_organisms[index]
                        logstr = logstr_dicts[index]
                        log_writer.write_data(logstr)
                        relaxed_organisms[index] = None
                        logstr_dicts[index] = ''

                        if num_finished_calcs % ncalcs_to_restart == 0:
                            thisRestart = RestartFile(0, num_finished_calcs,
                                                      garun_dir, objects_dict,
                                                      initial_population, whole_pop)
                            thisRestart.to_file()

                        # take care of relaxed organism
                        if relaxed_organism is not None:
                            geometry.unpad(relaxed_organism.cell, constraints)
                            if developer.develop(relaxed_organism,
                                                 composition_space,
                                                 constraints, geometry, pool, log_writer):
                                redundant_organism = \
                                    redundancy_guard.check_redundancy(
                                        relaxed_organism, whole_pop, geometry, log_writer)
                                if redundant_organism is not None:  # redundant
                                    if redundant_organism.is_active and \
                                            redundant_organism.epa > \
                                            relaxed_organism.epa:
                                        initial_population.replace_organism(
                                            redundant_organism,
                                            relaxed_organism,
                                            composition_space, log_writer)
                                        progress = \
                                            initial_population.get_progress(
                                                composition_space)
                                        data_writer.write_data(
                                            relaxed_organism,
                                            num_finished_calcs, progress)
                                        logstr = f'Number of energy calculations so far: {num_finished_calcs}'
                                        log_writer.write_data(logstr)
                                else:  # not redundant
                                    stopping_criteria.check_organism(
                                        relaxed_organism, redundancy_guard,
                                        geometry)
                                    initial_population.add_organism(
                                        relaxed_organism, composition_space, log_writer)
                                    whole_pop.append(relaxed_organism)
                                    progress = \
                                        initial_population.get_progress(
                                            composition_space)
                                    data_writer.write_data(
                                        relaxed_organism, num_finished_calcs,
                                        progress)
                                    logstr = f'Number of energy calculations so far: {num_finished_calcs}'
                                    log_writer.write_data(logstr)
                                    if creator.is_successes_based and \
                                            relaxed_organism.made_by == \
                                            creator.name:
                                        creator.update_status()

                        # make another organism for the initial population
                        started_new_calc = False
                        while not started_new_calc and not creator.is_finished:
                            new_organism = creator.create_organism(
                                id_generator, composition_space,
                                constraints, log_writer, random)
                            while new_organism is None and not \
                                    creator.is_finished:
                                new_organism = creator.create_organism(
                                    id_generator, composition_space,
                                    constraints, log_writer, random)
                            if new_organism is not None:
                                geometry.unpad(new_organism.cell, constraints)
                                if developer.develop(new_organism,
                                                     composition_space,
                                                     constraints, geometry,
                                                     pool, log_writer):
                                    redundant_organism = \
                                        redundancy_guard.check_redundancy(
                                            new_organism, whole_pop, geometry, log_writer)
                                    if redundant_organism is None:  # not redundant
                                        whole_pop.append(
                                            copy.deepcopy(new_organism))
                                        geometry.pad(new_organism.cell)
                                        stopping_criteria.update_calc_counter()
                                        new_thread = threading.Thread(
                                            target=energy_calculator.do_energy_calculation,
                                            args=[new_organism,
                                                  relaxed_organisms, logstr_dicts, index,
                                                  composition_space])
                                        new_thread.start()
                                        threads[index] = new_thread
                                        started_new_calc = True

    # depending on how the loop above exited, update bookkeeping
    if not stopping_criteria.are_satisfied:
        num_finished_calcs = num_finished_calcs - 1

    # process all the calculations that were still running when the last
    # creator finished
    num_to_get = num_calcs_at_once  # number of threads left to handle
    handled_indices = []  # the indices of the threads we've already handled

    while num_to_get > 0:
        for index, thread in enumerate(threads):
            if not thread.is_alive() and index not in handled_indices:
                num_finished_calcs += 1
                relaxed_organism = relaxed_organisms[index]
                logstr = logstr_dicts[index]
                log_writer.write_data(logstr)
                num_to_get = num_to_get - 1
                handled_indices.append(index)
                relaxed_organisms[index] = None
                logstr_dicts[index] = ''

                # take care of relaxed organism
                if relaxed_organism is not None:
                    geometry.unpad(relaxed_organism.cell, constraints)
                    if developer.develop(relaxed_organism, composition_space,
                                         constraints, geometry, pool, log_writer):
                        redundant_organism = redundancy_guard.check_redundancy(
                            relaxed_organism, whole_pop, geometry, log_writer)
                        if redundant_organism is not None:  # redundant
                            if redundant_organism.is_active and \
                                    redundant_organism.epa > \
                                    relaxed_organism.epa:
                                initial_population.replace_organism(
                                    redundant_organism, relaxed_organism,
                                    composition_space, log_writer)
                                progress = initial_population.get_progress(
                                    composition_space)
                                data_writer.write_data(relaxed_organism,
                                                       num_finished_calcs,
                                                       progress)
                                logstr = f'Number of energy calculations so far: {num_finished_calcs}'
                                log_writer.write_data(logstr)
                        else:  # no redundancy
                            stopping_criteria.check_organism(
                                relaxed_organism, redundancy_guard, geometry)
                            initial_population.add_organism(relaxed_organism,
                                                            composition_space, log_writer)
                            whole_pop.append(relaxed_organism)
                            progress = initial_population.get_progress(
                                composition_space)
                            data_writer.write_data(relaxed_organism,
                                                   num_finished_calcs,
                                                   progress)
                            logstr = f'Number of energy calculations so far: {num_finished_calcs}'
                            log_writer.write_data(logstr)

    # check if the stopping criteria were already met when making the initial
    # population
    if stopping_criteria.are_satisfied:
        quit()

    return objects_dict, whole_pop, num_finished_calcs, initial_population


def create_offsprings(objects_dict, garun_dir, data_writer, log_writer, THIS_PATH,
                      whole_pop, num_finished_calcs, initial_population,
                      offspring_generator):
    organism_creators = objects_dict['organism_creators']
    num_calcs_at_once = objects_dict['num_calcs_at_once']
    ncalcs_to_restart = objects_dict['num_calcs_to_restartfile']
    composition_space = objects_dict['composition_space']
    constraints = objects_dict['constraints']
    geometry = objects_dict['geometry']
    developer = objects_dict['developer']
    redundancy_guard = objects_dict['redundancy_guard']
    stopping_criteria = objects_dict['stopping_criteria']
    energy_calculator = objects_dict['energy_calculator']
    pool = objects_dict['pool']
    variations = objects_dict['variations']
    id_generator = objects_dict['id_generator']

    threads = []
    relaxed_organisms = {}
    logstr_dicts = {}
    # create the initial batch of offspring organisms and submit them for
    # energy calculations
    for _ in range(num_calcs_at_once):
        unrelaxed_offspring = offspring_generator.make_offspring_organism(
            random, pool, variations, geometry, id_generator, whole_pop,
            developer, redundancy_guard, composition_space, constraints, log_writer)
        whole_pop.append(copy.deepcopy(unrelaxed_offspring))
        geometry.pad(unrelaxed_offspring.cell)
        stopping_criteria.update_calc_counter()
        index = len(threads)
        new_thread = threading.Thread(
            target=energy_calculator.do_energy_calculation,
            args=[unrelaxed_offspring, relaxed_organisms, logstr_dicts, index,
                  composition_space])
        new_thread.start()
        threads.append(new_thread)

    # process finished calculations and start new ones
    while not stopping_criteria.are_satisfied:
        for index, thread in enumerate(threads):
            if not thread.is_alive():
                num_finished_calcs += 1
                relaxed_offspring = relaxed_organisms[index]
                logstr = logstr_dicts[index]
                log_writer.write_data(logstr)
                relaxed_organisms[index] = None
                logstr_dicts[index] = ''

                if num_finished_calcs % ncalcs_to_restart == 0:
                    thisRestart = RestartFile(1, num_finished_calcs,
                                              garun_dir, objects_dict,
                                              initial_population, whole_pop)
                    thisRestart.to_file()

                # take care of relaxed offspring organism
                if relaxed_offspring is not None:
                    geometry.unpad(relaxed_offspring.cell, constraints)
                    if developer.develop(relaxed_offspring, composition_space,
                                         constraints, geometry, pool, log_writer):
                        # check for redundancy with the the pool first
                        redundant_organism = redundancy_guard.check_redundancy(
                            relaxed_offspring, pool.to_list(), geometry, log_writer)
                        if redundant_organism is not None:  # redundant
                            if redundant_organism.epa > relaxed_offspring.epa:
                                pool.replace_organism(redundant_organism,
                                                      relaxed_offspring,
                                                      composition_space, log_writer)
                                pool.compute_fitnesses()
                                pool.compute_selection_probs()
                                pool.print_summary(composition_space, num_finished_calcs, log_writer)
                                progress = pool.get_progress(composition_space)
                                data_writer.write_data(relaxed_offspring,
                                                       num_finished_calcs,
                                                       progress)
                                logstr = f'Number of energy calculations so far: {num_finished_calcs}'
                                log_writer.write_data(logstr)

                        # check for redundancy with all the organisms
                        else:
                            redundant_organism = \
                                redundancy_guard.check_redundancy(
                                    relaxed_offspring, whole_pop, geometry, log_writer)
                        if redundant_organism is None:  # not redundant
                            stopping_criteria.check_organism(
                                relaxed_offspring, redundancy_guard, geometry)
                            pool.add_organism(relaxed_offspring,
                                              composition_space, log_writer)
                            whole_pop.append(relaxed_offspring)

                            # check if we've added enough new offspring
                            # organisms to the pool that we can remove the
                            # initial population organisms from the front
                            # (right end) of the queue.
                            if pool.num_adds == pool.size:
                                logstr = f'Removing the initial population from the pool'
                                log_writer.write_data(logstr)

                                for _ in range(len(
                                        initial_population.initial_population)):
                                    removed_org = pool.queue.pop()
                                    removed_org.is_active = False
                                    logstr = f'Removing organism {removed_org.id} from the pool'
                                    log_writer.write_data(logstr)

                            # if the initial population organisms have already
                            # been removed from the pool's queue, then just
                            # need to pop one organism from the front (right
                            # end) of the queue.
                            elif pool.num_adds > pool.size:
                                removed_org = pool.queue.pop()
                                removed_org.is_active = False
                                logstr = f'Removing organism {removed_org.id} from the pool'
                                log_writer.write_data(logstr)

                            pool.compute_fitnesses()
                            pool.compute_selection_probs()
                            pool.print_summary(composition_space, num_finished_calcs, log_writer)
                            progress = pool.get_progress(composition_space)
                            data_writer.write_data(relaxed_offspring,
                                                   num_finished_calcs,
                                                   progress)
                            logstr = f'Number of energy calculations so far: {num_finished_calcs}'
                            log_writer.write_data(logstr)

                # make another offspring organism
                if not stopping_criteria.are_satisfied:
                    unrelaxed_offspring = \
                        offspring_generator.make_offspring_organism(
                            random, pool, variations, geometry, id_generator,
                            whole_pop, developer, redundancy_guard,
                            composition_space, constraints, log_writer)
                    whole_pop.append(copy.deepcopy(unrelaxed_offspring))
                    geometry.pad(unrelaxed_offspring.cell)
                    stopping_criteria.update_calc_counter()
                    new_thread = threading.Thread(
                        target=energy_calculator.do_energy_calculation,
                        args=[unrelaxed_offspring, relaxed_organisms, logstr_dicts,
                              index, composition_space])
                    new_thread.start()
                    threads[index] = new_thread
    # process all the calculations that were still running when the
    # stopping criteria were achieved
    num_to_get = num_calcs_at_once  # how many threads we have left to handle
    handled_indices = []  # the indices of the threads we've already handled

    while num_to_get > 0:
        for index, thread in enumerate(threads):
            if not thread.is_alive() and index not in handled_indices:
                num_finished_calcs += 1
                relaxed_offspring = relaxed_organisms[index]
                logstr = logstr_dicts[index]
                log_writer.write_data(logstr)
                num_to_get -= 1
                handled_indices.append(index)
                relaxed_organisms[index] = None
                logstr_dicts[index] = ''
                # take care of relaxed offspring organism
                if relaxed_offspring is not None:
                    geometry.unpad(relaxed_offspring.cell, constraints)
                    if developer.develop(relaxed_offspring, composition_space,
                                         constraints, geometry, pool, log_writer):
                        # check for redundancy with the pool first
                        redundant_organism = redundancy_guard.check_redundancy(
                            relaxed_offspring, pool.to_list(), geometry)
                        if redundant_organism is not None:  # redundant
                            if redundant_organism.epa > relaxed_offspring.epa:
                                pool.replace_organism(redundant_organism,
                                                      relaxed_offspring,
                                                      composition_space, log_writer)
                                pool.compute_fitnesses()
                                pool.compute_selection_probs()
                                pool.print_summary(composition_space, num_finished_calcs, log_writer)
                                progress = pool.get_progress(composition_space)
                                data_writer.write_data(relaxed_offspring,
                                                       num_finished_calcs,
                                                       progress)
                                logstr = f'Number of energy calculations so far: {num_finished_calcs}'
                                log_writer.write_data(logstr)
                        # check for redundancy with all the organisms
                        else:
                            redundant_organism = \
                                redundancy_guard.check_redundancy(
                                    relaxed_offspring, whole_pop, geometry, log_writer)
                        if redundant_organism is None:  # not redundant
                            pool.add_organism(relaxed_offspring,
                                              composition_space, log_writer)
                            whole_pop.append(relaxed_offspring)
                            removed_org = pool.queue.pop()
                            removed_org.is_active = False
                            logstr = f'Removing organism {removed_org.id} from the pool'
                            log_writer.write_data(logstr)
                            pool.compute_fitnesses()
                            pool.compute_selection_probs()
                            pool.print_summary(composition_space, num_finished_calcs, num_finished_calcs, log_writer)
                            progress = pool.get_progress(composition_space)
                            data_writer.write_data(relaxed_offspring,
                                                   num_finished_calcs,
                                                   progress)
                            logstr = f'Number of energy calculations so far: {num_finished_calcs}'
                            log_writer.write_data(logstr)

    return objects_dict, whole_pop, num_finished_calcs


def process(objects_dict, garun_dir, data_writer, log_writer, thisRestart, THIS_PATH):
    if thisRestart is None:
        whole_pop = []
        num_finished_calcs = 0
        initial_population = population.InitialPopulation(objects_dict['run_dir_name'])
        progress_index = 0
    else:
        whole_pop = copy.deepcopy(thisRestart.whole_pop)
        num_finished_calcs = thisRestart.num_finished_calcs
        initial_population = copy.deepcopy(thisRestart.initial_population)
        progress_index = thisRestart.progress_index
        thisRestart = None

    os.chdir(garun_dir)

    if progress_index == 0:
        objects_dict, whole_pop, num_finished_calcs, initial_population = creat_organisms(
            objects_dict, garun_dir, data_writer, log_writer, THIS_PATH,
            whole_pop, num_finished_calcs, initial_population)

        #os.chdir(THIS_PATH)
        objects_dict['pool'].add_initial_population(initial_population, objects_dict['composition_space'], log_writer)

    offspring_generator = general.OffspringGenerator()
    os.chdir(garun_dir)
    objects_dict, whole_pop, num_finished_calcs = create_offsprings(objects_dict, garun_dir, data_writer, log_writer,
                                                                    THIS_PATH,
                                                                    whole_pop, num_finished_calcs, initial_population,
                                                                    offspring_generator)
