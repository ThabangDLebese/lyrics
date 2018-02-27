import tensorflow as tf
import numpy as np
import utils
import functions
from functions import *
from fuzzy import LogicFactory
import re
import copy
import constants
class World(object):

    def __init__(self, logic="lukasiewicz"):

        #Map from domain name to domain object
        self.domains = {}

        #Map from function name to function object
        self.functions = {}

        #Map from relation name to relation object
        self.relations = {}

        #Map from individual id to individual object
        self.individuals = {}

        #This is a storage for already computed function
        self._precomputed = {}

        self.logic = LogicFactory.create(logic)

        self.loss = tf.constant(0., name="WorldLoss")


current_world = World()
from parser import Constant, FOLParser



class Domain(object):
    def __init__(self, label, data, dom_type=tf.float32):
        if label in current_world.domains:
            raise Exception("Domain %s already exists" % label)
        self.dom_type = dom_type
        self.label = label
        assert isinstance(data, tf.Tensor) or len(data)>0, "You need to provide at least one element of the domain %s" % (label)
        self.tensor = tf.convert_to_tensor(data)
        assert len(self.tensor.get_shape())==2, "Data for domain %s must be a two-dimensional tensor(i.e. matrix)" % self.label

        current_world.domains[self.label] = self

        #Map from individual id to the corresponding row inside the domain
        self.individuals = {} #TODO

    def add_individual(self, individual):
        self.tensor = tf.concat((self.tensor, individual.tensor), axis=0)
        self.individuals[individual.label]=self


class Individual(object):
    def __init__(self, label, domain, value=None):
        if label in current_world.individuals:
            raise Exception("Duplicate individual id %s " % label)
        self.label = label
        if isinstance(domain, str):
            self.domain = current_world.domains[domain]
        if value is not None:
            self.tensor = tf.constant([value], dtype=tf.float32, name=label)
            assert(self.tensor.get_shape()[1]==self.domain.tensor.get_shape()[1],"The individual shape '%s' does not match with the '%s' domain shape" % (self.label, self.domain.label))
            self.columns = len(value)
        else:
            self.columns = domain.columns
            self.tensor = tf.Variable(tf.random_normal([1, self.columns], mean=1), name=label)
        current_world.individuals[self.label] = self
        self.domain.individuals[self.label] = tf.shape(self.domain.tensor)[0]

def compute_domains_tensor(domains):

    num_domains = len(domains)
    domains_rows= [tf.shape(domain.tensor)[0] for domain in domains]
    domains_columns = [tf.shape(domain.tensor)[1] for domain in domains]
    tensors = []
    for i,domain in enumerate(domains):
        tensor = domain.tensor


        to_reshape = [1 for _ in range(num_domains)]
        to_reshape[i] = domains_rows[i]
        to_reshape = to_reshape+ [domains_columns[i]]
        tensor = tf.reshape(tensor, to_reshape)


        to_repeat = copy.copy(domains_rows)
        to_repeat[i] = 1
        to_repeat = to_repeat+[1]
        tensor = tf.tile(tensor, to_repeat)


        tensor = tf.reshape(tensor, [-1, domains_columns[i]])
        tensors.append(tensor)

    return tensors

class Function(object):
    def __init__(self, label, domains, function):
        if label in current_world.functions:
            raise Exception("Function %s already exists" % label)
        self.label = label

        if utils.isIterableNotString(domains):
            domains = list(domains)
            for i in range(len(domains)):
                if isinstance(domains[i], str):
                    domains[i] = current_world.domains[domains[i]]
            self.domains = tuple(domains)  # tuple of domains
        else:
            if isinstance(domains, str):
                domains = current_world.domains[domains]
            self.domains = (domains,)
        current_world.functions[label] = self
        self.arity = len(self.domains)


        if function is None:
            raise NotImplementedError("Default functions implementation in Function not yet implemented")
        else:
            self.function = function

        if isinstance(self.function, functions.Slice):
            father_function = self.function.function
            if constants.DOMAINS_VALUE + str(father_function) not in current_world._precomputed:
                domains_cartesian_tensors = compute_domains_tensor(self.domains)
                current_world._precomputed[constants.DOMAINS_VALUE + str(father_function)] = father_function.call(
                    *domains_cartesian_tensors)
        with tf.variable_scope(constants.DOMAINS_VALUE + label):
            if isinstance(function, functions.Slice):
                current_world._precomputed[constants.DOMAINS_VALUE + label] = \
                    current_world._precomputed[constants.DOMAINS_VALUE + str(self.function.function)][:,
                    self.function.axis]
            else:
                if self.arity == 1:
                    domains_cartesian_tensors = [self.domains[0].tensor]
                else:
                    domains_cartesian_tensors = compute_domains_tensor(self.domains)
                current_world._precomputed[constants.DOMAINS_VALUE + label] = self.function.call(
                    *domains_cartesian_tensors)


class Relation(object):
    def __init__(self, label, domains, function=None):
        if label in current_world.relations:
            raise Exception("Relation %s already exists" % label)
        self.label = label

        if utils.isIterableNotString(domains):
            domains = list(domains)
            for i in range(len(domains)):
                if isinstance(domains[i], str):
                    domains[i] = current_world.domains[domains[i]]
            self.domains = tuple(domains)  # tuple of domains
        else:
            if isinstance(domains, str):
                domains = current_world.domains[domains]
            self.domains = (domains,)
        current_world.relations[label] = self
        self.arity = len(self.domains)
        if function is None:
            raise NotImplementedError("Default function implementation in Relation not yet implemented")
        else:
            self.function = function

        if isinstance(self.function, functions.Slice):
            father_function = self.function.function
            if constants.DOMAINS_VALUE+str(father_function) not in current_world._precomputed:
                domains_cartesian_tensors = compute_domains_tensor(self.domains)
                current_world._precomputed[constants.DOMAINS_VALUE + str(father_function)] = father_function.call(
                    *domains_cartesian_tensors)
        with tf.variable_scope(constants.DOMAINS_VALUE+label):
            if isinstance(function, functions.Slice):
                current_world._precomputed[constants.DOMAINS_VALUE+label] = \
                    current_world._precomputed[constants.DOMAINS_VALUE + str(self.function.function)][:, self.function.axis]
            else:
                if self.arity == 1:
                    domains_cartesian_tensors = [self.domains[0].tensor]
                else:
                    domains_cartesian_tensors = compute_domains_tensor(self.domains)
                current_world._precomputed[constants.DOMAINS_VALUE+label] = self.function.call(*domains_cartesian_tensors)




class PointwiseConstraint(object):


    def __init__(self, output, labels, inputs):
        if isinstance(output, functions.Learner):
            current_world.loss += output.cost(labels, inputs)
        # TODO other cases of output (i.e. CLARE.Relation or CLARE.Function)


class RegularizationConstraint(object):

    def __init__(self, function, weight):
        if isinstance(function, functions.RegularizedLearner):
            current_world.loss += weight * function.regularization_cost()
        # TODO other cases of output (i.e. CLARE.Relation or CLARE.Function)

class Constraint(object):


    def __init__(self, definition, weight=1.0):



        # String of the formula
        self.definition = definition

        # String of variable
        self.ambiguos_variables = {}

        # Each constraint will have a set of variables
        self.variables_dict = {}
        self.variables_list = []
        self.variable_indices = {}

        # Each constraint will have a set of variables
        self.constant_dict = {}

        # We keep track of the columns range associated to each variable
        self.last_column = 0

        # Parsing the FOL formula
        parser = FOLParser()
        self.root = parser.parse(self.definition, constraint=self)

        with tf.name_scope(re.sub('[^0-9a-zA-Z_]', '', self.definition)):

            with tf.name_scope("CartesianShape"):
                # This is the shape of the multi-dimensional tensor, where each dimension corresponds to a variable
                if len(self.variables_list)>0: #not gounded formula
                    try:
                        self.cartesian_shape = [tf.shape(a.domain.tensor)[0] for a in self.variables_list]
                    except AttributeError: #None domain for a variable
                        raise Exception("In constraint [%s], a variable has not been used in any predicate or function" % self.definition)
                else:
                    self.cartesian_shape = [1]


            # Compiling the expression tree
            self.root.compile()
            self.tensor = self.root.tensor

        # Adding a loss term to
        # tf.summary.scalar("Contraints/" + "_".join(definition.split()), 1 - self.tensor)
        # constraints_l += (1 - self.tensor)
        current_world.loss += weight * (1 - self.tensor)


def learn(learning_rate=0.001, num_epochs=1000, print_iters=1, sess=None, vars = None, eval=None):
    if vars is None:
        train_op = tf.train.AdamOptimizer(learning_rate).minimize(current_world.loss)
        sess.run(tf.global_variables_initializer())
    else:
        with tf.variable_scope("SpecializedRun"):
            train_op = tf.train.AdamOptimizer(learning_rate).minimize(current_world.loss, var_list=vars)
        sess.run(tf.variables_initializer(tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope="SpecializedRun")))
        sess.run([v.initializer for v in vars])
    if sess is None:
        sess = tf.Session()
        sess.run(tf.global_variables_initializer())


    for i in range(num_epochs):
        if i%print_iters==0 and eval is not None:
            _, val = sess.run((train_op,eval))
            print(val)
        else:
            _ = sess.run(train_op)




