# -*- coding: utf-8 -*-
"""
Contains data structures and utilities for hyde.
"""
import codecs
import yaml
from datetime import datetime

from commando.util import getLoggerWithNullHandler
from fswrap import File, Folder

from hyde._compat import iteritems, str, UserDict

logger = getLoggerWithNullHandler('hyde.engine')

SEQS = (tuple, list, set, frozenset)


def make_expando(primitive):
    """
    Creates an expando object, a sequence of expando objects or just
    returns the primitive based on the primitive's type.
    """
    if isinstance(primitive, dict):
        return Expando(primitive)
    elif isinstance(primitive, SEQS):
        seq = type(primitive)
        return seq(make_expando(attr) for attr in primitive)
    else:
        return primitive


class Expando(object):

    """
    A generic expando class that creates attributes from
    the passed in dictionary.
    """

    def __init__(self, d):
        super(Expando, self).__init__()
        self.update(d)

    def __iter__(self):
        """
        Returns an iterator for all the items in the
        dictionary as key value pairs.
        """
        return iteritems(self.__dict__)

    def update(self, d):
        """
        Updates the expando with a new dictionary
        """
        d = d or {}
        if isinstance(d, dict):
            for key, value in d.items():
                self.set_expando(key, value)
        elif isinstance(d, Expando):
            self.update(d.to_dict())

    def set_expando(self, key, value):
        """
        Sets the expando attribute after
        transforming the value.
        """
        setattr(self, str(key), make_expando(value))

    def __repr__(self):
        return str(self.to_dict())

    def to_dict(self):
        """
        Reverse transform an expando to dict
        """
        result = {}
        d = self.__dict__
        for k, v in d.items():
            if isinstance(v, Expando):
                result[k] = v.to_dict()
            elif isinstance(v, SEQS):
                seq = type(v)
                result[k] = seq(item.to_dict()
                                if isinstance(item, Expando)
                                else item for item in v
                                )
            else:
                result[k] = v
        return result

    def get(self, key, default=None):
        """
        Dict like get helper method
        """
        return self.__dict__.get(key, default)


class Context(object):

    """
    Wraps the context related functions and utilities.
    """

    @staticmethod
    def load(sitepath, ctx):
        """
        Load context from config data and providers.
        """
        context = {}
        try:
            context.update(ctx.data.__dict__)
        except AttributeError:
            # No context data found
            pass

        providers = {}
        try:
            providers.update(ctx.providers.__dict__)
        except AttributeError:
            # No providers found
            pass

        for provider_name, resource_name in providers.items():
            res = File(Folder(sitepath).child(resource_name))
            if res.exists:
                data = make_expando(yaml.load(res.read_all(), Loader=yaml.FullLoader))
                context[provider_name] = data

        return context


class Dependents(UserDict):

    """
    Represents the dependency graph for hyde.
    """

    def __init__(self, sitepath, depends_file_name='.hyde_deps'):
        self.sitepath = Folder(sitepath)
        self.deps_file = File(self.sitepath.child(depends_file_name))
        self.data = {}
        if self.deps_file.exists:
            self.data = yaml.load(self.deps_file.read_all(), Loader=yaml.FullLoader)
        import atexit
        atexit.register(self.save)

    def save(self):
        """
        Saves the dependency graph (just a dict for now).
        """
        if self.deps_file.parent.exists:
            self.deps_file.write(yaml.dump(self.data))


def _expand_path(sitepath, path):
    child = sitepath.child_folder(path)
    return Folder(child.fully_expanded_path)


class Config(Expando):

    """
    Represents the hyde configuration file
    """

    def __init__(self, sitepath, config_file=None, config_dict=None):
        self.default_config = dict(
            mode='production',
            simple_copy=[],
            content_root='content',
            deploy_root='deploy',
            media_root='media',
            layout_root='layout',
            media_url='/media',
            base_url="/",
            encode_safe=None,
            not_found='404.html',
            plugins=[],
            ignore=["*~", "*.bak", ".hg", ".git", ".svn"],
            meta={
                "nodemeta": 'meta.yaml'
            }
        )
        self.config_file = config_file
        self.config_dict = config_dict
        self.load_time = datetime.min
        self.config_files = []
        self.sitepath = Folder(sitepath)
        super(Config, self).__init__(self.load())

    @property
    def last_modified(self):
        return max((conf.last_modified for conf in self.config_files))

    def needs_refresh(self):
        if not self.config_files:
            return True
        return any((conf.has_changed_since(self.load_time)
                    for conf in self.config_files))

    def load(self):
        conf = dict(**self.default_config)
        conf.update(self.read_config(self.config_file))
        if self.config_dict:
            conf.update(self.config_dict)
        return conf

    def reload(self):
        if not self.config_file:
            return
        self.update(self.load())

    def read_config(self, config_file):
        """
        Reads the configuration file and updates this
        object while allowing for inherited configurations.
        """
        conf_file = self.sitepath.child(
            config_file if
            config_file else 'site.yaml')
        conf = {}
        if File(conf_file).exists:
            self.config_files.append(File(conf_file))
            logger.info("Reading site configuration from [%s]", conf_file)
            with codecs.open(conf_file, 'r', 'utf-8') as stream:
                conf = yaml.load(stream, Loader=yaml.FullLoader)
                if 'extends' in conf:
                    parent = self.read_config(conf['extends'])
                    parent.update(conf)
                    conf = parent
        self.load_time = datetime.now()
        return conf

    @property
    def deploy_root_path(self):
        """
        Derives the deploy root path from the site path
        """
        return _expand_path(self.sitepath, self.deploy_root)

    @property
    def content_root_path(self):
        """
        Derives the content root path from the site path
        """
        return _expand_path(self.sitepath, self.content_root)

    @property
    def media_root_path(self):
        """
        Derives the media root path from the content path
        """
        path = Folder(self.content_root).child(self.media_root)
        return _expand_path(self.sitepath, path)

    @property
    def layout_root_path(self):
        """
        Derives the layout root path from the site path
        """
        return _expand_path(self.sitepath, self.layout_root)
