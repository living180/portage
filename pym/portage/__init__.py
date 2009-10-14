# portage.py -- core Portage functionality
# Copyright 1998-2009 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2
# $Id$

from __future__ import print_function

VERSION="$Rev$"[6:-2] + "-svn"

# ===========================================================================
# START OF IMPORTS -- START OF IMPORTS -- START OF IMPORTS -- START OF IMPORT
# ===========================================================================

try:
	import sys
	import codecs
	import copy
	import errno
	if not hasattr(errno, 'ESTALE'):
		# ESTALE may not be defined on some systems, such as interix.
		errno.ESTALE = -1
	import logging
	import re
	import time
	import types
	try:
		import cPickle as pickle
	except ImportError:
		import pickle

	import stat
	try:
		from subprocess import getstatusoutput as subprocess_getstatusoutput
	except ImportError:
		from commands import getstatusoutput as subprocess_getstatusoutput
	from time import sleep
	from random import shuffle
	from itertools import chain
	import platform
	import warnings

	# Temporarily delete these imports, to ensure that only the
	# wrapped versions are imported by portage internals.
	import os
	del os
	import shutil
	del shutil

except ImportError as e:
	sys.stderr.write("\n\n")
	sys.stderr.write("!!! Failed to complete python imports. These are internal modules for\n")
	sys.stderr.write("!!! python and failure here indicates that you have a problem with python\n")
	sys.stderr.write("!!! itself and thus portage is not able to continue processing.\n\n")

	sys.stderr.write("!!! You might consider starting python with verbose flags to see what has\n")
	sys.stderr.write("!!! gone wrong. Here is the information we got for this exception:\n")
	sys.stderr.write("    "+str(e)+"\n\n");
	raise

try:
	from portage.cache.cache_errors import CacheError
	import portage.proxy.lazyimport
	import portage.proxy as proxy
	proxy.lazyimport.lazyimport(globals(),
		'portage.checksum',
		'portage.checksum:perform_checksum,perform_md5,prelink_capable',
		'portage.cvstree',
		'portage.data',
		'portage.data:lchown,ostype,portage_gid,portage_uid,secpass,' + \
			'uid,userland,userpriv_groups,wheelgid',
		'portage.dep',
		'portage.dep:best_match_to_list,dep_getcpv,dep_getkey,' + \
			'get_operator,isjustname,isspecific,isvalidatom,' + \
			'match_from_list,match_to_list',
		'portage.eclass_cache',
		'portage.env.loaders',
		'portage.exception',
		'portage.getbinpkg',
		'portage.locks',
		'portage.locks:lockdir,lockfile,unlockdir,unlockfile',
		'portage.mail',
		'portage.output',
		'portage.output:bold,colorize',
		'portage.process',
		'portage.process:atexit_register,run_exitfuncs',
		'portage.update:dep_transform,fixdbentries,grab_updates,' + \
			'parse_updates,update_config_files,update_dbentries,' + \
			'update_dbentry',
		'portage.util',
		'portage.util:atomic_ofstream,apply_secpass_permissions,' + \
			'apply_recursive_permissions,dump_traceback,getconfig,' + \
			'grabdict,grabdict_package,grabfile,grabfile_package,' + \
			'map_dictlist_vals,new_protect_filename,normalize_path,' + \
			'pickle_read,pickle_write,stack_dictlist,stack_dicts,' + \
			'stack_lists,unique_array,varexpand,writedict,writemsg,' + \
			'writemsg_stdout,write_atomic',
		'portage.versions',
		'portage.versions:best,catpkgsplit,catsplit,endversion_keys,' + \
			'suffix_value@endversion,pkgcmp,pkgsplit,vercmp,ververify',
		'portage.xpak',
	)

	import portage.const
	from portage.const import VDB_PATH, PRIVATE_PATH, CACHE_PATH, DEPCACHE_PATH, \
		USER_CONFIG_PATH, MODULES_FILE_PATH, CUSTOM_PROFILE_PATH, PORTAGE_BASE_PATH, \
		PORTAGE_BIN_PATH, PORTAGE_PYM_PATH, PROFILE_PATH, LOCALE_DATA_PATH, \
		EBUILD_SH_BINARY, SANDBOX_BINARY, BASH_BINARY, \
		MOVE_BINARY, PRELINK_BINARY, WORLD_FILE, MAKE_CONF_FILE, MAKE_DEFAULTS_FILE, \
		DEPRECATED_PROFILE_FILE, USER_VIRTUALS_FILE, EBUILD_SH_ENV_FILE, \
		INVALID_ENV_FILE, CUSTOM_MIRRORS_FILE, CONFIG_MEMORY_FILE,\
		INCREMENTALS, EAPI, MISC_SH_BINARY, REPO_NAME_LOC, REPO_NAME_FILE

	from portage.localization import _

except ImportError as e:
	sys.stderr.write("\n\n")
	sys.stderr.write("!!! Failed to complete portage imports. There are internal modules for\n")
	sys.stderr.write("!!! portage and failure here indicates that you have a problem with your\n")
	sys.stderr.write("!!! installation of portage. Please try a rescue portage located in the\n")
	sys.stderr.write("!!! portage tree under '/usr/portage/sys-apps/portage/files/' (default).\n")
	sys.stderr.write("!!! There is a README.RESCUE file that details the steps required to perform\n")
	sys.stderr.write("!!! a recovery of portage.\n")
	sys.stderr.write("    "+str(e)+"\n\n")
	raise

if sys.hexversion >= 0x3000000:
	basestring = str
	long = int

# Assume utf_8 fs encoding everywhere except in merge code, where the
# user's locale is respected.
_encodings = {
	'content'                : 'utf_8',
	'fs'                     : 'utf_8',
	'merge'                  : sys.getfilesystemencoding(),
	'repo.content'           : 'utf_8',
	'stdio'                  : 'utf_8',
}

# This can happen if python is built with USE=build (stage 1).
if _encodings['merge'] is None:
	_encodings['merge'] = 'ascii'

if sys.hexversion >= 0x3000000:
	def _unicode_encode(s, encoding=_encodings['content'], errors='backslashreplace'):
		if isinstance(s, str):
			s = s.encode(encoding, errors)
		return s

	def _unicode_decode(s, encoding=_encodings['content'], errors='replace'):
		if isinstance(s, bytes):
			s = str(s, encoding=encoding, errors=errors)
		return s
else:
	def _unicode_encode(s, encoding=_encodings['content'], errors='backslashreplace'):
		if isinstance(s, unicode):
			s = s.encode(encoding, errors)
		return s

	def _unicode_decode(s, encoding=_encodings['content'], errors='replace'):
		if isinstance(s, bytes):
			s = unicode(s, encoding=encoding, errors=errors)
		return s

class _unicode_func_wrapper(object):
	"""
	Wraps a function, converts arguments from unicode to bytes,
	and return values to unicode from bytes. Function calls
	will raise UnicodeEncodeError if an argument fails to be
	encoded with the required encoding. Return values that
	are single strings are decoded with errors='replace'. Return 
	values that are lists of strings are decoded with errors='strict'
	and elements that fail to be decoded are omitted from the returned
	list.
	"""
	__slots__ = ('_func', '_encoding')

	def __init__(self, func, encoding=_encodings['fs']):
		self._func = func
		self._encoding = encoding

	def __call__(self, *args, **kwargs):

		encoding = self._encoding
		wrapped_args = [_unicode_encode(x, encoding=encoding, errors='strict')
			for x in args]
		if kwargs:
			wrapped_kwargs = dict(
				(k, _unicode_encode(v, encoding=encoding, errors='strict'))
				for k, v in kwargs.items())
		else:
			wrapped_kwargs = {}

		rval = self._func(*wrapped_args, **wrapped_kwargs)

		if isinstance(rval, (list, tuple)):
			decoded_rval = []
			for x in rval:
				try:
					x = _unicode_decode(x, encoding=encoding, errors='strict')
				except UnicodeDecodeError:
					pass
				else:
					decoded_rval.append(x)

			if isinstance(rval, tuple):
				rval = tuple(decoded_rval)
			else:
				rval = decoded_rval
		else:
			rval = _unicode_decode(rval, encoding=encoding, errors='replace')

		return rval

class _unicode_module_wrapper(object):
	"""
	Wraps a module and wraps all functions with _unicode_func_wrapper.
	"""
	__slots__ = ('_mod', '_encoding', '_overrides', '_cache')

	def __init__(self, mod, encoding=_encodings['fs'], overrides=None, cache=True):
		object.__setattr__(self, '_mod', mod)
		object.__setattr__(self, '_encoding', encoding)
		object.__setattr__(self, '_overrides', overrides)
		if cache:
			cache = {}
		else:
			cache = None
		object.__setattr__(self, '_cache', cache)

	def __getattribute__(self, attr):
		cache = object.__getattribute__(self, '_cache')
		if cache is not None:
			result = cache.get(attr)
			if result is not None:
				return result
		result = getattr(object.__getattribute__(self, '_mod'), attr)
		encoding = object.__getattribute__(self, '_encoding')
		overrides = object.__getattribute__(self, '_overrides')
		override = None
		if overrides is not None:
			override = overrides.get(id(result))
		if override is not None:
			result = override
		elif isinstance(result, type):
			pass
		elif type(result) is types.ModuleType:
			result = _unicode_module_wrapper(result,
				encoding=encoding, overrides=overrides)
		elif hasattr(result, '__call__'):
			result = _unicode_func_wrapper(result, encoding=encoding)
		if cache is not None:
			cache[attr] = result
		return result

import os as _os
_os_overrides = {
	id(_os.fdopen)        : _os.fdopen,
	id(_os.popen)         : _os.popen,
	id(_os.read)          : _os.read,
	id(_os.system)        : _os.system,
}

if hasattr(_os, 'statvfs'):
	_os_overrides[id(_os.statvfs)] = _os.statvfs

os = _unicode_module_wrapper(_os, overrides=_os_overrides,
	encoding=_encodings['fs'])
_os_merge = _unicode_module_wrapper(_os,
	encoding=_encodings['merge'], overrides=_os_overrides)

import shutil as _shutil
shutil = _unicode_module_wrapper(_shutil, encoding=_encodings['fs'])

# Imports below this point rely on the above unicode wrapper definitions.
_selinux = None
selinux = None
_selinux_merge = None
try:
	import portage._selinux
	selinux = _unicode_module_wrapper(_selinux,
		encoding=_encodings['fs'])
	_selinux_merge = _unicode_module_wrapper(_selinux,
		encoding=_encodings['merge'])
except OSError as e:
	sys.stderr.write("!!! SELinux not loaded: %s\n" % str(e))
	del e
except ImportError:
	pass

from portage.manifest import Manifest

# ===========================================================================
# END OF IMPORTS -- END OF IMPORTS -- END OF IMPORTS -- END OF IMPORTS -- END
# ===========================================================================

def _gen_missing_encodings(missing_encodings):

	encodings = {}

	if 'ascii' in missing_encodings:

		class AsciiIncrementalEncoder(codecs.IncrementalEncoder):
			def encode(self, input, final=False):
				return codecs.ascii_encode(input, self.errors)[0]

		class AsciiIncrementalDecoder(codecs.IncrementalDecoder):
			def decode(self, input, final=False):
				return codecs.ascii_decode(input, self.errors)[0]

		class AsciiStreamWriter(codecs.StreamWriter):
			encode = codecs.ascii_encode

		class AsciiStreamReader(codecs.StreamReader):
			decode = codecs.ascii_decode

		codec_info =  codecs.CodecInfo(
			name='ascii',
			encode=codecs.ascii_encode,
			decode=codecs.ascii_decode,
			incrementalencoder=AsciiIncrementalEncoder,
			incrementaldecoder=AsciiIncrementalDecoder,
			streamwriter=AsciiStreamWriter,
			streamreader=AsciiStreamReader,
		)

		for alias in ('ascii', '646', 'ansi_x3.4_1968', 'ansi_x3_4_1968',
			'ansi_x3.4_1986', 'cp367', 'csascii', 'ibm367', 'iso646_us',
			'iso_646.irv_1991', 'iso_ir_6', 'us', 'us_ascii'):
			encodings[alias] = codec_info

	if 'utf_8' in missing_encodings:

		def utf8decode(input, errors='strict'):
			return codecs.utf_8_decode(input, errors, True)

		class Utf8IncrementalEncoder(codecs.IncrementalEncoder):
			def encode(self, input, final=False):
				return codecs.utf_8_encode(input, self.errors)[0]

		class Utf8IncrementalDecoder(codecs.BufferedIncrementalDecoder):
			_buffer_decode = codecs.utf_8_decode

		class Utf8StreamWriter(codecs.StreamWriter):
			encode = codecs.utf_8_encode

		class Utf8StreamReader(codecs.StreamReader):
			decode = codecs.utf_8_decode

		codec_info = codecs.CodecInfo(
			name='utf-8',
			encode=codecs.utf_8_encode,
			decode=utf8decode,
			incrementalencoder=Utf8IncrementalEncoder,
			incrementaldecoder=Utf8IncrementalDecoder,
			streamreader=Utf8StreamReader,
			streamwriter=Utf8StreamWriter,
		)

		for alias in ('utf_8', 'u8', 'utf', 'utf8', 'utf8_ucs2', 'utf8_ucs4'):
			encodings[alias] = codec_info

	return encodings

def _ensure_default_encoding():
	"""
	The python that's inside stage 1 or 2 is built with a minimal
	configuration which does not include the /usr/lib/pythonX.Y/encodings
	directory. This results in error like the following:

	  LookupError: no codec search functions registered: can't find encoding

	In order to solve this problem, detect it early and manually register
	a search function for the ascii and utf_8 codecs. Starting with python-3.0
	this problem is more noticeable because of stricter handling of encoding
	and decoding between strings of characters and bytes.
	"""

	default_fallback = 'utf_8'
	default_encoding = sys.getdefaultencoding().lower().replace('-', '_')
	filesystem_encoding = _encodings['merge'].lower().replace('-', '_')
	required_encodings = set(['ascii', 'utf_8'])
	required_encodings.add(default_encoding)
	required_encodings.add(filesystem_encoding)
	missing_encodings = set()
	for codec_name in required_encodings:
		try:
			codecs.lookup(codec_name)
		except LookupError:
			missing_encodings.add(codec_name)

	if not missing_encodings:
		return

	encodings = _gen_missing_encodings(missing_encodings)

	if default_encoding in missing_encodings and \
		default_encoding not in encodings:
		# Make the fallback codec correspond to whatever name happens
		# to be returned by sys.getfilesystemencoding().

		try:
			encodings[default_encoding] = codecs.lookup(default_fallback)
		except LookupError:
			encodings[default_encoding] = encodings[default_fallback]

	if filesystem_encoding in missing_encodings and \
		filesystem_encoding not in encodings:
		# Make the fallback codec correspond to whatever name happens
		# to be returned by sys.getdefaultencoding().

		try:
			encodings[filesystem_encoding] = codecs.lookup(default_fallback)
		except LookupError:
			encodings[filesystem_encoding] = encodings[default_fallback]

	def search_function(name):
		name = name.lower()
		name = name.replace('-', '_')
		codec_info = encodings.get(name)
		if codec_info is not None:
			return codecs.CodecInfo(
				name=codec_info.name,
				encode=codec_info.encode,
				decode=codec_info.decode,
				incrementalencoder=codec_info.incrementalencoder,
				incrementaldecoder=codec_info.incrementaldecoder,
				streamreader=codec_info.streamreader,
				streamwriter=codec_info.streamwriter,
			)
		return None

	codecs.register(search_function)

	del codec_name, default_encoding, default_fallback, \
		filesystem_encoding, missing_encodings, \
		required_encodings, search_function

# Do this ASAP since writemsg() might not work without it.
_ensure_default_encoding()

def _shell_quote(s):
	"""
	Quote a string in double-quotes and use backslashes to
	escape any backslashes, double-quotes, dollar signs, or
	backquotes in the string.
	"""
	for letter in "\\\"$`":
		if letter in s:
			s = s.replace(letter, "\\" + letter)
	return "\"%s\"" % s

bsd_chflags = None

if platform.system() in ('FreeBSD',):

	class bsd_chflags(object):

		@classmethod
		def chflags(cls, path, flags, opts=""):
			cmd = 'chflags %s %o %s' % (opts, flags, _shell_quote(path))
			status, output = subprocess_getstatusoutput(cmd)
			if os.WIFEXITED(status) and os.WEXITSTATUS(status) == os.EX_OK:
				return
			# Try to generate an ENOENT error if appropriate.
			if 'h' in opts:
				_os_merge.lstat(path)
			else:
				_os_merge.stat(path)
			# Make sure the binary exists.
			if not portage.process.find_binary('chflags'):
				raise portage.exception.CommandNotFound('chflags')
			# Now we're not sure exactly why it failed or what
			# the real errno was, so just report EPERM.
			e = OSError(errno.EPERM, output)
			e.errno = errno.EPERM
			e.filename = path
			e.message = output
			raise e

		@classmethod
		def lchflags(cls, path, flags):
			return cls.chflags(path, flags, opts='-h')

def load_mod(name):
	modname = ".".join(name.split(".")[:-1])
	mod = __import__(modname)
	components = name.split('.')
	for comp in components[1:]:
		mod = getattr(mod, comp)
	return mod

def best_from_dict(key, top_dict, key_order, EmptyOnError=1, FullCopy=1, AllowEmpty=1):
	for x in key_order:
		if x in top_dict and key in top_dict[x]:
			if FullCopy:
				return copy.deepcopy(top_dict[x][key])
			else:
				return top_dict[x][key]
	if EmptyOnError:
		return ""
	else:
		raise KeyError("Key not found in list; '%s'" % key)

def getcwd():
	"this fixes situations where the current directory doesn't exist"
	try:
		return os.getcwd()
	except OSError: #dir doesn't exist
		os.chdir("/")
		return "/"
getcwd()

def abssymlink(symlink):
	"This reads symlinks, resolving the relative symlinks, and returning the absolute."
	mylink=os.readlink(symlink)
	if mylink[0] != '/':
		mydir=os.path.dirname(symlink)
		mylink=mydir+"/"+mylink
	return os.path.normpath(mylink)

dircache = {}
cacheHit=0
cacheMiss=0
cacheStale=0
def cacheddir(my_original_path, ignorecvs, ignorelist, EmptyOnError, followSymlinks=True):
	global cacheHit,cacheMiss,cacheStale
	mypath = normalize_path(my_original_path)
	if mypath in dircache:
		cacheHit += 1
		cached_mtime, list, ftype = dircache[mypath]
	else:
		cacheMiss += 1
		cached_mtime, list, ftype = -1, [], []
	try:
		pathstat = os.stat(mypath)
		if stat.S_ISDIR(pathstat[stat.ST_MODE]):
			mtime = pathstat.st_mtime
		else:
			raise portage.exception.DirectoryNotFound(mypath)
	except EnvironmentError as e:
		if e.errno == portage.exception.PermissionDenied.errno:
			raise portage.exception.PermissionDenied(mypath)
		del e
		if EmptyOnError:
			return [], []
		return None, None
	except portage.exception.PortageException:
		if EmptyOnError:
			return [], []
		return None, None
	# Python retuns mtime in seconds, so if it was changed in the last few seconds, it could be invalid
	if mtime != cached_mtime or time.time() - mtime < 4:
		if mypath in dircache:
			cacheStale += 1
		try:
			list = os.listdir(mypath)
		except EnvironmentError as e:
			if e.errno != errno.EACCES:
				raise
			del e
			raise portage.exception.PermissionDenied(mypath)
		ftype = []
		for x in list:
			try:
				if followSymlinks:
					pathstat = os.stat(mypath+"/"+x)
				else:
					pathstat = os.lstat(mypath+"/"+x)

				if stat.S_ISREG(pathstat[stat.ST_MODE]):
					ftype.append(0)
				elif stat.S_ISDIR(pathstat[stat.ST_MODE]):
					ftype.append(1)
				elif stat.S_ISLNK(pathstat[stat.ST_MODE]):
					ftype.append(2)
				else:
					ftype.append(3)
			except (IOError, OSError):
				ftype.append(3)
		dircache[mypath] = mtime, list, ftype

	ret_list = []
	ret_ftype = []
	for x in range(0, len(list)):
		if list[x] in ignorelist:
			pass
		elif ignorecvs:
			if list[x][:2] != ".#":
				ret_list.append(list[x])
				ret_ftype.append(ftype[x])
		else:
			ret_list.append(list[x])
			ret_ftype.append(ftype[x])

	writemsg("cacheddirStats: H:%d/M:%d/S:%d\n" % (cacheHit, cacheMiss, cacheStale),10)
	return ret_list, ret_ftype

_ignorecvs_dirs = ('CVS', 'SCCS', '.svn', '.git')

def listdir(mypath, recursive=False, filesonly=False, ignorecvs=False, ignorelist=[], followSymlinks=True,
	EmptyOnError=False, dirsonly=False):
	"""
	Portage-specific implementation of os.listdir

	@param mypath: Path whose contents you wish to list
	@type mypath: String
	@param recursive: Recursively scan directories contained within mypath
	@type recursive: Boolean
	@param filesonly; Only return files, not more directories
	@type filesonly: Boolean
	@param ignorecvs: Ignore CVS directories ('CVS','SCCS','.svn','.git')
	@type ignorecvs: Boolean
	@param ignorelist: List of filenames/directories to exclude
	@type ignorelist: List
	@param followSymlinks: Follow Symlink'd files and directories
	@type followSymlinks: Boolean
	@param EmptyOnError: Return [] if an error occurs.
	@type EmptyOnError: Boolean
	@param dirsonly: Only return directories.
	@type dirsonly: Boolean
	@rtype: List
	@returns: A list of files and directories (or just files or just directories) or an empty list.
	"""

	list, ftype = cacheddir(mypath, ignorecvs, ignorelist, EmptyOnError, followSymlinks)

	if list is None:
		list=[]
	if ftype is None:
		ftype=[]

	if not (filesonly or dirsonly or recursive):
		return list

	if recursive:
		x=0
		while x<len(ftype):
			if ftype[x] == 1 and not \
				(ignorecvs and os.path.basename(list[x]) in _ignorecvs_dirs):
				l,f = cacheddir(mypath+"/"+list[x], ignorecvs, ignorelist, EmptyOnError,
					followSymlinks)

				l=l[:]
				for y in range(0,len(l)):
					l[y]=list[x]+"/"+l[y]
				list=list+l
				ftype=ftype+f
			x+=1
	if filesonly:
		rlist=[]
		for x in range(0,len(ftype)):
			if ftype[x]==0:
				rlist=rlist+[list[x]]
	elif dirsonly:
		rlist = []
		for x in range(0, len(ftype)):
			if ftype[x] == 1:
				rlist = rlist + [list[x]]	
	else:
		rlist=list

	return rlist

def flatten(mytokens):
	"""this function now turns a [1,[2,3]] list into
	a [1,2,3] list and returns it."""
	newlist=[]
	for x in mytokens:
		if isinstance(x, list):
			newlist.extend(flatten(x))
		else:
			newlist.append(x)
	return newlist

#beautiful directed graph object

class digraph(object):
	def __init__(self):
		"""Create an empty digraph"""
		
		# { node : ( { child : priority } , { parent : priority } ) }
		self.nodes = {}
		self.order = []

	def add(self, node, parent, priority=0):
		"""Adds the specified node with the specified parent.
		
		If the dep is a soft-dep and the node already has a hard
		relationship to the parent, the relationship is left as hard."""
		
		if node not in self.nodes:
			self.nodes[node] = ({}, {}, node)
			self.order.append(node)
		
		if not parent:
			return
		
		if parent not in self.nodes:
			self.nodes[parent] = ({}, {}, parent)
			self.order.append(parent)

		priorities = self.nodes[node][1].get(parent)
		if priorities is None:
			priorities = []
			self.nodes[node][1][parent] = priorities
			self.nodes[parent][0][node] = priorities
		priorities.append(priority)
		priorities.sort()

	def remove(self, node):
		"""Removes the specified node from the digraph, also removing
		and ties to other nodes in the digraph. Raises KeyError if the
		node doesn't exist."""
		
		if node not in self.nodes:
			raise KeyError(node)
		
		for parent in self.nodes[node][1]:
			del self.nodes[parent][0][node]
		for child in self.nodes[node][0]:
			del self.nodes[child][1][node]
		
		del self.nodes[node]
		self.order.remove(node)

	def difference_update(self, t):
		"""
		Remove all given nodes from node_set. This is more efficient
		than multiple calls to the remove() method.
		"""
		if isinstance(t, (list, tuple)) or \
			not hasattr(t, "__contains__"):
			t = frozenset(t)
		order = []
		for node in self.order:
			if node not in t:
				order.append(node)
				continue
			for parent in self.nodes[node][1]:
				del self.nodes[parent][0][node]
			for child in self.nodes[node][0]:
				del self.nodes[child][1][node]
			del self.nodes[node]
		self.order = order

	def remove_edge(self, child, parent):
		"""
		Remove edge in the direction from child to parent. Note that it is
		possible for a remaining edge to exist in the opposite direction.
		Any endpoint vertices that become isolated will remain in the graph.
		"""

		# Nothing should be modified when a KeyError is raised.
		for k in parent, child:
			if k not in self.nodes:
				raise KeyError(k)

		# Make sure the edge exists.
		if child not in self.nodes[parent][0]:
			raise KeyError(child)
		if parent not in self.nodes[child][1]:
			raise KeyError(parent)

		# Remove the edge.
		del self.nodes[child][1][parent]
		del self.nodes[parent][0][child]

	def __iter__(self):
		return iter(self.order)

	def contains(self, node):
		"""Checks if the digraph contains mynode"""
		return node in self.nodes

	def get(self, key, default=None):
		node_data = self.nodes.get(key, self)
		if node_data is self:
			return default
		return node_data[2]

	def all_nodes(self):
		"""Return a list of all nodes in the graph"""
		return self.order[:]

	def child_nodes(self, node, ignore_priority=None):
		"""Return all children of the specified node"""
		if ignore_priority is None:
			return list(self.nodes[node][0])
		children = []
		if hasattr(ignore_priority, '__call__'):
			for child, priorities in self.nodes[node][0].items():
				for priority in priorities:
					if not ignore_priority(priority):
						children.append(child)
						break
		else:
			for child, priorities in self.nodes[node][0].items():
				if ignore_priority < priorities[-1]:
					children.append(child)
		return children

	def parent_nodes(self, node, ignore_priority=None):
		"""Return all parents of the specified node"""
		if ignore_priority is None:
			return list(self.nodes[node][1])
		parents = []
		if hasattr(ignore_priority, '__call__'):
			for parent, priorities in self.nodes[node][1].items():
				for priority in priorities:
					if not ignore_priority(priority):
						parents.append(parent)
						break
		else:
			for parent, priorities in self.nodes[node][1].items():
				if ignore_priority < priorities[-1]:
					parents.append(parent)
		return parents

	def leaf_nodes(self, ignore_priority=None):
		"""Return all nodes that have no children
		
		If ignore_soft_deps is True, soft deps are not counted as
		children in calculations."""
		
		leaf_nodes = []
		if ignore_priority is None:
			for node in self.order:
				if not self.nodes[node][0]:
					leaf_nodes.append(node)
		elif hasattr(ignore_priority, '__call__'):
			for node in self.order:
				is_leaf_node = True
				for child, priorities in self.nodes[node][0].items():
					for priority in priorities:
						if not ignore_priority(priority):
							is_leaf_node = False
							break
					if not is_leaf_node:
						break
				if is_leaf_node:
					leaf_nodes.append(node)
		else:
			for node in self.order:
				is_leaf_node = True
				for child, priorities in self.nodes[node][0].items():
					if ignore_priority < priorities[-1]:
						is_leaf_node = False
						break
				if is_leaf_node:
					leaf_nodes.append(node)
		return leaf_nodes

	def root_nodes(self, ignore_priority=None):
		"""Return all nodes that have no parents.
		
		If ignore_soft_deps is True, soft deps are not counted as
		parents in calculations."""
		
		root_nodes = []
		if ignore_priority is None:
			for node in self.order:
				if not self.nodes[node][1]:
					root_nodes.append(node)
		elif hasattr(ignore_priority, '__call__'):
			for node in self.order:
				is_root_node = True
				for parent, priorities in self.nodes[node][1].items():
					for priority in priorities:
						if not ignore_priority(priority):
							is_root_node = False
							break
					if not is_root_node:
						break
				if is_root_node:
					root_nodes.append(node)
		else:
			for node in self.order:
				is_root_node = True
				for parent, priorities in self.nodes[node][1].items():
					if ignore_priority < priorities[-1]:
						is_root_node = False
						break
				if is_root_node:
					root_nodes.append(node)
		return root_nodes

	def is_empty(self):
		"""Checks if the digraph is empty"""
		return len(self.nodes) == 0

	def clone(self):
		clone = digraph()
		clone.nodes = {}
		memo = {}
		for children, parents, node in self.nodes.values():
			children_clone = {}
			for child, priorities in children.items():
				priorities_clone = memo.get(id(priorities))
				if priorities_clone is None:
					priorities_clone = priorities[:]
					memo[id(priorities)] = priorities_clone
				children_clone[child] = priorities_clone
			parents_clone = {}
			for parent, priorities in parents.items():
				priorities_clone = memo.get(id(priorities))
				if priorities_clone is None:
					priorities_clone = priorities[:]
					memo[id(priorities)] = priorities_clone
				parents_clone[parent] = priorities_clone
			clone.nodes[node] = (children_clone, parents_clone, node)
		clone.order = self.order[:]
		return clone

	# Backward compatibility
	addnode = add
	allnodes = all_nodes
	allzeros = leaf_nodes
	hasnode = contains
	__contains__ = contains
	empty = is_empty
	copy = clone

	def delnode(self, node):
		try:
			self.remove(node)
		except KeyError:
			pass

	def firstzero(self):
		leaf_nodes = self.leaf_nodes()
		if leaf_nodes:
			return leaf_nodes[0]
		return None

	def hasallzeros(self, ignore_priority=None):
		return len(self.leaf_nodes(ignore_priority=ignore_priority)) == \
			len(self.order)

	def debug_print(self):
		def output(s):
			writemsg(s, noiselevel=-1)
		for node in self.nodes:
			output("%s " % (node,))
			if self.nodes[node][0]:
				output("depends on\n")
			else:
				output("(no children)\n")
			for child, priorities in self.nodes[node][0].items():
				output("  %s (%s)\n" % (child, priorities[-1],))

#parse /etc/env.d and generate /etc/profile.env

def env_update(makelinks=1, target_root=None, prev_mtimes=None, contents=None,
	env=None, writemsg_level=None):
	if writemsg_level is None:
		writemsg_level = portage.util.writemsg_level
	if target_root is None:
		global settings
		target_root = settings["ROOT"]
	if prev_mtimes is None:
		global mtimedb
		prev_mtimes = mtimedb["ldpath"]
	if env is None:
		env = os.environ
	envd_dir = os.path.join(target_root, "etc", "env.d")
	portage.util.ensure_dirs(envd_dir, mode=0o755)
	fns = listdir(envd_dir, EmptyOnError=1)
	fns.sort()
	templist = []
	for x in fns:
		if len(x) < 3:
			continue
		if not x[0].isdigit() or not x[1].isdigit():
			continue
		if x.startswith(".") or x.endswith("~") or x.endswith(".bak"):
			continue
		templist.append(x)
	fns = templist
	del templist

	space_separated = set(["CONFIG_PROTECT", "CONFIG_PROTECT_MASK"])
	colon_separated = set(["ADA_INCLUDE_PATH", "ADA_OBJECTS_PATH",
		"CLASSPATH", "INFODIR", "INFOPATH", "KDEDIRS", "LDPATH", "MANPATH",
		  "PATH", "PKG_CONFIG_PATH", "PRELINK_PATH", "PRELINK_PATH_MASK",
		  "PYTHONPATH", "ROOTPATH"])

	config_list = []

	for x in fns:
		file_path = os.path.join(envd_dir, x)
		try:
			myconfig = getconfig(file_path, expand=False)
		except portage.exception.ParseError as e:
			writemsg("!!! '%s'\n" % str(e), noiselevel=-1)
			del e
			continue
		if myconfig is None:
			# broken symlink or file removed by a concurrent process
			writemsg("!!! File Not Found: '%s'\n" % file_path, noiselevel=-1)
			continue

		config_list.append(myconfig)
		if "SPACE_SEPARATED" in myconfig:
			space_separated.update(myconfig["SPACE_SEPARATED"].split())
			del myconfig["SPACE_SEPARATED"]
		if "COLON_SEPARATED" in myconfig:
			colon_separated.update(myconfig["COLON_SEPARATED"].split())
			del myconfig["COLON_SEPARATED"]

	env = {}
	specials = {}
	for var in space_separated:
		mylist = []
		for myconfig in config_list:
			if var in myconfig:
				for item in myconfig[var].split():
					if item and not item in mylist:
						mylist.append(item)
				del myconfig[var] # prepare for env.update(myconfig)
		if mylist:
			env[var] = " ".join(mylist)
		specials[var] = mylist

	for var in colon_separated:
		mylist = []
		for myconfig in config_list:
			if var in myconfig:
				for item in myconfig[var].split(":"):
					if item and not item in mylist:
						mylist.append(item)
				del myconfig[var] # prepare for env.update(myconfig)
		if mylist:
			env[var] = ":".join(mylist)
		specials[var] = mylist

	for myconfig in config_list:
		"""Cumulative variables have already been deleted from myconfig so that
		they won't be overwritten by this dict.update call."""
		env.update(myconfig)

	ldsoconf_path = os.path.join(target_root, "etc", "ld.so.conf")
	try:
		myld = codecs.open(_unicode_encode(ldsoconf_path,
			encoding=_encodings['fs'], errors='strict'),
			mode='r', encoding=_encodings['content'], errors='replace')
		myldlines=myld.readlines()
		myld.close()
		oldld=[]
		for x in myldlines:
			#each line has at least one char (a newline)
			if x[0]=="#":
				continue
			oldld.append(x[:-1])
	except (IOError, OSError) as e:
		if e.errno != errno.ENOENT:
			raise
		oldld = None

	ld_cache_update=False

	newld = specials["LDPATH"]
	if (oldld!=newld):
		#ld.so.conf needs updating and ldconfig needs to be run
		myfd = atomic_ofstream(ldsoconf_path)
		myfd.write("# ld.so.conf autogenerated by env-update; make all changes to\n")
		myfd.write("# contents of /etc/env.d directory\n")
		for x in specials["LDPATH"]:
			myfd.write(x+"\n")
		myfd.close()
		ld_cache_update=True

	# Update prelink.conf if we are prelink-enabled
	if prelink_capable:
		newprelink = atomic_ofstream(
			os.path.join(target_root, "etc", "prelink.conf"))
		newprelink.write("# prelink.conf autogenerated by env-update; make all changes to\n")
		newprelink.write("# contents of /etc/env.d directory\n")

		for x in ["/bin","/sbin","/usr/bin","/usr/sbin","/lib","/usr/lib"]:
			newprelink.write("-l "+x+"\n");
		for x in specials["LDPATH"]+specials["PATH"]+specials["PRELINK_PATH"]:
			if not x:
				continue
			if x[-1]!='/':
				x=x+"/"
			plmasked=0
			for y in specials["PRELINK_PATH_MASK"]:
				if not y:
					continue
				if y[-1]!='/':
					y=y+"/"
				if y==x[0:len(y)]:
					plmasked=1
					break
			if not plmasked:
				newprelink.write("-h "+x+"\n")
		for x in specials["PRELINK_PATH_MASK"]:
			newprelink.write("-b "+x+"\n")
		newprelink.close()

	# Portage stores mtimes with 1 second granularity but in >=python-2.5 finer
	# granularity is possible.  In order to avoid the potential ambiguity of
	# mtimes that differ by less than 1 second, sleep here if any of the
	# directories have been modified during the current second.
	sleep_for_mtime_granularity = False
	current_time = long(time.time())
	mtime_changed = False
	lib_dirs = set()
	for lib_dir in portage.util.unique_array(specials["LDPATH"]+['usr/lib','usr/lib64','usr/lib32','lib','lib64','lib32']):
		x = os.path.join(target_root, lib_dir.lstrip(os.sep))
		try:
			newldpathtime = long(os.stat(x).st_mtime)
			lib_dirs.add(normalize_path(x))
		except OSError as oe:
			if oe.errno == errno.ENOENT:
				try:
					del prev_mtimes[x]
				except KeyError:
					pass
				# ignore this path because it doesn't exist
				continue
			raise
		if newldpathtime == current_time:
			sleep_for_mtime_granularity = True
		if x in prev_mtimes:
			if prev_mtimes[x] == newldpathtime:
				pass
			else:
				prev_mtimes[x] = newldpathtime
				mtime_changed = True
		else:
			prev_mtimes[x] = newldpathtime
			mtime_changed = True

	if mtime_changed:
		ld_cache_update = True

	if makelinks and \
		not ld_cache_update and \
		contents is not None:
		libdir_contents_changed = False
		for mypath, mydata in contents.items():
			if mydata[0] not in ("obj","sym"):
				continue
			head, tail = os.path.split(mypath)
			if head in lib_dirs:
				libdir_contents_changed = True
				break
		if not libdir_contents_changed:
			makelinks = False

	ldconfig = "/sbin/ldconfig"
	if "CHOST" in env and "CBUILD" in env and \
		env["CHOST"] != env["CBUILD"]:
		from portage.process import find_binary
		ldconfig = find_binary("%s-ldconfig" % env["CHOST"])

	# Only run ldconfig as needed
	if (ld_cache_update or makelinks) and ldconfig:
		# ldconfig has very different behaviour between FreeBSD and Linux
		if ostype=="Linux" or ostype.lower().endswith("gnu"):
			# We can't update links if we haven't cleaned other versions first, as
			# an older package installed ON TOP of a newer version will cause ldconfig
			# to overwrite the symlinks we just made. -X means no links. After 'clean'
			# we can safely create links.
			writemsg_level(_(">>> Regenerating %setc/ld.so.cache...\n") % \
				(target_root,))
			if makelinks:
				os.system("cd / ; %s -r '%s'" % (ldconfig, target_root))
			else:
				os.system("cd / ; %s -X -r '%s'" % (ldconfig, target_root))
		elif ostype in ("FreeBSD","DragonFly"):
			writemsg_level(_(">>> Regenerating %svar/run/ld-elf.so.hints...\n") % \
				target_root)
			os.system(("cd / ; %s -elf -i " + \
				"-f '%svar/run/ld-elf.so.hints' '%setc/ld.so.conf'") % \
				(ldconfig, target_root, target_root))

	del specials["LDPATH"]

	penvnotice  = "# THIS FILE IS AUTOMATICALLY GENERATED BY env-update.\n"
	penvnotice += "# DO NOT EDIT THIS FILE. CHANGES TO STARTUP PROFILES\n"
	cenvnotice  = penvnotice[:]
	penvnotice += "# GO INTO /etc/profile NOT /etc/profile.env\n\n"
	cenvnotice += "# GO INTO /etc/csh.cshrc NOT /etc/csh.env\n\n"

	#create /etc/profile.env for bash support
	outfile = atomic_ofstream(os.path.join(target_root, "etc", "profile.env"))
	outfile.write(penvnotice)

	env_keys = [ x for x in env if x != "LDPATH" ]
	env_keys.sort()
	for k in env_keys:
		v = env[k]
		if v.startswith('$') and not v.startswith('${'):
			outfile.write("export %s=$'%s'\n" % (k, v[1:]))
		else:
			outfile.write("export %s='%s'\n" % (k, v))
	outfile.close()

	#create /etc/csh.env for (t)csh support
	outfile = atomic_ofstream(os.path.join(target_root, "etc", "csh.env"))
	outfile.write(cenvnotice)
	for x in env_keys:
		outfile.write("setenv %s '%s'\n" % (x, env[x]))
	outfile.close()

	if sleep_for_mtime_granularity:
		while current_time == long(time.time()):
			sleep(1)

def ExtractKernelVersion(base_dir):
	"""
	Try to figure out what kernel version we are running
	@param base_dir: Path to sources (usually /usr/src/linux)
	@type base_dir: string
	@rtype: tuple( version[string], error[string])
	@returns:
	1. tuple( version[string], error[string])
	Either version or error is populated (but never both)

	"""
	lines = []
	pathname = os.path.join(base_dir, 'Makefile')
	try:
		f = codecs.open(_unicode_encode(pathname,
			encoding=_encodings['fs'], errors='strict'), mode='r',
			encoding=_encodings['content'], errors='replace')
	except OSError as details:
		return (None, str(details))
	except IOError as details:
		return (None, str(details))

	try:
		for i in range(4):
			lines.append(f.readline())
	except OSError as details:
		return (None, str(details))
	except IOError as details:
		return (None, str(details))

	lines = [l.strip() for l in lines]

	version = ''

	#XXX: The following code relies on the ordering of vars within the Makefile
	for line in lines:
		# split on the '=' then remove annoying whitespace
		items = line.split("=")
		items = [i.strip() for i in items]
		if items[0] == 'VERSION' or \
			items[0] == 'PATCHLEVEL':
			version += items[1]
			version += "."
		elif items[0] == 'SUBLEVEL':
			version += items[1]
		elif items[0] == 'EXTRAVERSION' and \
			items[-1] != items[0]:
			version += items[1]

	# Grab a list of files named localversion* and sort them
	localversions = os.listdir(base_dir)
	for x in range(len(localversions)-1,-1,-1):
		if localversions[x][:12] != "localversion":
			del localversions[x]
	localversions.sort()

	# Append the contents of each to the version string, stripping ALL whitespace
	for lv in localversions:
		version += "".join( " ".join( grabfile( base_dir+ "/" + lv ) ).split() )

	# Check the .config for a CONFIG_LOCALVERSION and append that too, also stripping whitespace
	kernelconfig = getconfig(base_dir+"/.config")
	if kernelconfig and "CONFIG_LOCALVERSION" in kernelconfig:
		version += "".join(kernelconfig["CONFIG_LOCALVERSION"].split())

	return (version,None)

def autouse(myvartree, use_cache=1, mysettings=None):
	"""
	autuse returns a list of USE variables auto-enabled to packages being installed

	@param myvartree: Instance of the vartree class (from /var/db/pkg...)
	@type myvartree: vartree
	@param use_cache: read values from cache
	@type use_cache: Boolean
	@param mysettings: Instance of config
	@type mysettings: config
	@rtype: string
	@returns: A string containing a list of USE variables that are enabled via use.defaults
	"""
	if mysettings is None:
		global settings
		mysettings = settings
	if mysettings.profile_path is None:
		return ""
	myusevars=""
	usedefaults = mysettings.use_defs
	for myuse in usedefaults:
		dep_met = True
		for mydep in usedefaults[myuse]:
			if not myvartree.dep_match(mydep,use_cache=True):
				dep_met = False
				break
		if dep_met:
			myusevars += " "+myuse
	return myusevars

def check_config_instance(test):
	if not isinstance(test, config):
		raise TypeError("Invalid type for config object: %s (should be %s)" % (test.__class__, config))

def _lazy_iuse_regex(iuse_implicit):
	"""
	The PORTAGE_IUSE value is lazily evaluated since re.escape() is slow
	and the value is only used when an ebuild phase needs to be executed
	(it's used only to generate QA notices).
	"""
	# Escape anything except ".*" which is supposed to pass through from
	# _get_implicit_iuse().
	regex = sorted(re.escape(x) for x in iuse_implicit)
	regex = "^(%s)$" % "|".join(regex)
	regex = regex.replace("\\.\\*", ".*")
	return regex

class _local_repo_config(object):
	__slots__ = ('aliases', 'eclass_overrides', 'masters', 'name',)
	def __init__(self, name, repo_opts):
		self.name = name

		aliases = repo_opts.get('aliases')
		if aliases is not None:
			aliases = tuple(aliases.split())
		self.aliases = aliases

		eclass_overrides = repo_opts.get('eclass-overrides')
		if eclass_overrides is not None:
			eclass_overrides = tuple(eclass_overrides.split())
		self.eclass_overrides = eclass_overrides

		masters = repo_opts.get('masters')
		if masters is not None:
			masters = tuple(masters.split())
		self.masters = masters

class config(object):
	"""
	This class encompasses the main portage configuration.  Data is pulled from
	ROOT/PORTDIR/profiles/, from ROOT/etc/make.profile incrementally through all 
	parent profiles as well as from ROOT/PORTAGE_CONFIGROOT/* for user specified
	overrides.
	
	Generally if you need data like USE flags, FEATURES, environment variables,
	virtuals ...etc you look in here.
	"""

	# Don't include anything that could be extremely long here (like SRC_URI)
	# since that could cause execve() calls to fail with E2BIG errors. For
	# example, see bug #262647.
	_setcpv_aux_keys = ('SLOT', 'RESTRICT', 'LICENSE',
		'KEYWORDS',  'INHERITED', 'IUSE', 'PROVIDE', 'EAPI',
		'PROPERTIES', 'DEFINED_PHASES', 'repository')

	_env_blacklist = [
		"A", "AA", "CATEGORY", "DEPEND", "DESCRIPTION", "EAPI",
		"EBUILD_PHASE", "EMERGE_FROM", "HOMEPAGE", "INHERITED", "IUSE",
		"KEYWORDS", "LICENSE", "PDEPEND", "PF", "PKGUSE",
		"PORTAGE_CONFIGROOT", "PORTAGE_IUSE",
		"PORTAGE_NONFATAL", "PORTAGE_REPO_NAME",
		"PORTAGE_USE", "PROPERTIES", "PROVIDE", "RDEPEND", "RESTRICT",
		"ROOT", "SLOT", "SRC_URI"
	]

	_environ_whitelist = []

	# Whitelisted variables are always allowed to enter the ebuild
	# environment. Generally, this only includes special portage
	# variables. Ebuilds can unset variables that are not whitelisted
	# and rely on them remaining unset for future phases, without them
	# leaking back in from various locations (bug #189417). It's very
	# important to set our special BASH_ENV variable in the ebuild
	# environment in order to prevent sandbox from sourcing /etc/profile
	# in it's bashrc (causing major leakage).
	_environ_whitelist += [
		"ACCEPT_LICENSE", "BASH_ENV", "BUILD_PREFIX", "D",
		"DISTDIR", "DOC_SYMLINKS_DIR", "EBUILD",
		"EBUILD_EXIT_STATUS_FILE", "EBUILD_FORCE_TEST",
		"EBUILD_PHASE", "ECLASSDIR", "ECLASS_DEPTH", "EMERGE_FROM",
		"FEATURES", "FILESDIR", "HOME", "NOCOLOR", "PATH",
		"PKGDIR",
		"PKGUSE", "PKG_LOGDIR", "PKG_TMPDIR",
		"PORTAGE_ACTUAL_DISTDIR", "PORTAGE_ARCHLIST",
		"PORTAGE_BASHRC",
		"PORTAGE_BINPKG_FILE", "PORTAGE_BINPKG_TAR_OPTS",
		"PORTAGE_BINPKG_TMPFILE",
		"PORTAGE_BIN_PATH",
		"PORTAGE_BUILDDIR", "PORTAGE_COLORMAP",
		"PORTAGE_CONFIGROOT", "PORTAGE_DEBUG", "PORTAGE_DEPCACHEDIR",
		"PORTAGE_GID", "PORTAGE_INST_GID", "PORTAGE_INST_UID",
		"PORTAGE_IUSE",
		"PORTAGE_LOG_FILE", "PORTAGE_MASTER_PID",
		"PORTAGE_PYM_PATH", "PORTAGE_QUIET",
		"PORTAGE_REPO_NAME", "PORTAGE_RESTRICT",
		"PORTAGE_TMPDIR", "PORTAGE_UPDATE_ENV",
		"PORTAGE_VERBOSE", "PORTAGE_WORKDIR_MODE",
		"PORTDIR", "PORTDIR_OVERLAY", "PREROOTPATH", "PROFILE_PATHS",
		"ROOT", "ROOTPATH", "STARTDIR", "T", "TMP", "TMPDIR",
		"USE_EXPAND", "USE_ORDER", "WORKDIR",
		"XARGS",
	]

	# user config variables
	_environ_whitelist += [
		"DOC_SYMLINKS_DIR", "INSTALL_MASK", "PKG_INSTALL_MASK"
	]

	_environ_whitelist += [
		"A", "AA", "CATEGORY", "P", "PF", "PN", "PR", "PV", "PVR"
	]

	# misc variables inherited from the calling environment
	_environ_whitelist += [
		"COLORTERM", "DISPLAY", "EDITOR", "LESS",
		"LESSOPEN", "LOGNAME", "LS_COLORS", "PAGER",
		"TERM", "TERMCAP", "USER",
	]

	# other variables inherited from the calling environment
	_environ_whitelist += [
		"CVS_RSH", "ECHANGELOG_USER",
		"GPG_AGENT_INFO",
		"SSH_AGENT_PID", "SSH_AUTH_SOCK",
		"STY", "WINDOW", "XAUTHORITY",
	]

	_environ_whitelist = frozenset(_environ_whitelist)

	_environ_whitelist_re = re.compile(r'^(CCACHE_|DISTCC_).*')

	# Filter selected variables in the config.environ() method so that
	# they don't needlessly propagate down into the ebuild environment.
	_environ_filter = []

	# misc variables inherited from the calling environment
	_environ_filter += [
		"INFOPATH", "MANPATH",
	]

	# variables that break bash
	_environ_filter += [
		"HISTFILE", "POSIXLY_CORRECT",
	]

	# portage config variables and variables set directly by portage
	_environ_filter += [
		"ACCEPT_KEYWORDS", "ACCEPT_PROPERTIES", "AUTOCLEAN",
		"CLEAN_DELAY", "COLLISION_IGNORE", "CONFIG_PROTECT",
		"CONFIG_PROTECT_MASK", "EGENCACHE_DEFAULT_OPTS", "EMERGE_DEFAULT_OPTS",
		"EMERGE_LOG_DIR",
		"EMERGE_WARNING_DELAY", "FETCHCOMMAND", "FETCHCOMMAND_FTP",
		"FETCHCOMMAND_HTTP", "FETCHCOMMAND_SFTP",
		"GENTOO_MIRRORS", "NOCONFMEM", "O",
		"PORTAGE_BACKGROUND",
		"PORTAGE_BINHOST_CHUNKSIZE", "PORTAGE_CALLER",
		"PORTAGE_ELOG_CLASSES",
		"PORTAGE_ELOG_MAILFROM", "PORTAGE_ELOG_MAILSUBJECT",
		"PORTAGE_ELOG_MAILURI", "PORTAGE_ELOG_SYSTEM",
		"PORTAGE_FETCH_CHECKSUM_TRY_MIRRORS", "PORTAGE_FETCH_RESUME_MIN_SIZE",
		"PORTAGE_GPG_DIR",
		"PORTAGE_GPG_KEY", "PORTAGE_IONICE_COMMAND",
		"PORTAGE_PACKAGE_EMPTY_ABORT",
		"PORTAGE_REPO_DUPLICATE_WARN",
		"PORTAGE_RO_DISTDIRS",
		"PORTAGE_RSYNC_EXTRA_OPTS", "PORTAGE_RSYNC_OPTS",
		"PORTAGE_RSYNC_RETRIES", "PORTAGE_USE", "PORT_LOGDIR",
		"QUICKPKG_DEFAULT_OPTS",
		"RESUMECOMMAND", "RESUMECOMMAND_HTTP", "RESUMECOMMAND_HTTP",
		"RESUMECOMMAND_SFTP", "SYNC", "USE_EXPAND_HIDDEN", "USE_ORDER",
	]

	_environ_filter = frozenset(_environ_filter)

	_undef_lic_groups = set()
	_default_globals = (
		('ACCEPT_LICENSE',           '* -@EULA'),
		('ACCEPT_PROPERTIES',        '*'),
	)

	# To enhance usability, make some vars case insensitive
	# by forcing them to lower case.
	_case_insensitive_vars = ('AUTOCLEAN', 'NOCOLOR',)

	def __init__(self, clone=None, mycpv=None, config_profile_path=None,
		config_incrementals=None, config_root=None, target_root=None,
		local_config=True, env=None):
		"""
		@param clone: If provided, init will use deepcopy to copy by value the instance.
		@type clone: Instance of config class.
		@param mycpv: CPV to load up (see setcpv), this is the same as calling init with mycpv=None
		and then calling instance.setcpv(mycpv).
		@type mycpv: String
		@param config_profile_path: Configurable path to the profile (usually PROFILE_PATH from portage.const)
		@type config_profile_path: String
		@param config_incrementals: List of incremental variables
			(defaults to portage.const.INCREMENTALS)
		@type config_incrementals: List
		@param config_root: path to read local config from (defaults to "/", see PORTAGE_CONFIGROOT)
		@type config_root: String
		@param target_root: __init__ override of $ROOT env variable.
		@type target_root: String
		@param local_config: Enables loading of local config (/etc/portage); used most by repoman to
		ignore local config (keywording and unmasking)
		@type local_config: Boolean
		@param env: The calling environment which is used to override settings.
			Defaults to os.environ if unspecified.
		@type env: dict
		"""

		# When initializing the global portage.settings instance, avoid
		# raising exceptions whenever possible since exceptions thrown
		# from 'import portage' or 'import portage.exceptions' statements
		# can practically render the api unusable for api consumers.
		tolerant = "_initializing_globals" in globals()

		self.already_in_regenerate = 0

		self.locked   = 0
		self.mycpv    = None
		self._setcpv_args_hash = None
		self.puse     = []
		self.modifiedkeys = []
		self.uvlist = []
		self._accept_chost_re = None
		self._accept_license = None
		self._accept_license_str = None
		self._license_groups = {}
		self._accept_properties = None

		self.virtuals = {}
		self.virts_p = {}
		self.dirVirtuals = None
		self.v_count  = 0

		# Virtuals obtained from the vartree
		self.treeVirtuals = {}
		# Virtuals by user specification. Includes negatives.
		self.userVirtuals = {}
		# Virtual negatives from user specifications.
		self.negVirtuals  = {}
		# Virtuals added by the depgraph via self.setinst().
		self._depgraphVirtuals = {}

		self.user_profile_dir = None
		self.local_config = local_config
		self._local_repo_configs = None
		self._local_repo_conf_path = None

		if clone:
			self.incrementals = copy.deepcopy(clone.incrementals)
			self.profile_path = copy.deepcopy(clone.profile_path)
			self.user_profile_dir = copy.deepcopy(clone.user_profile_dir)
			self.local_config = copy.deepcopy(clone.local_config)
			self._local_repo_configs = \
				copy.deepcopy(clone._local_repo_configs)
			self._local_repo_conf_path = \
				copy.deepcopy(clone._local_repo_conf_path)

			self.module_priority = copy.deepcopy(clone.module_priority)
			self.modules         = copy.deepcopy(clone.modules)

			self.depcachedir = copy.deepcopy(clone.depcachedir)

			self.packages = copy.deepcopy(clone.packages)
			self.virtuals = copy.deepcopy(clone.virtuals)

			self.dirVirtuals = copy.deepcopy(clone.dirVirtuals)
			self.treeVirtuals = copy.deepcopy(clone.treeVirtuals)
			self.userVirtuals = copy.deepcopy(clone.userVirtuals)
			self.negVirtuals  = copy.deepcopy(clone.negVirtuals)
			self._depgraphVirtuals = copy.deepcopy(clone._depgraphVirtuals)

			self.use_defs = copy.deepcopy(clone.use_defs)
			self.usemask  = copy.deepcopy(clone.usemask)
			self.usemask_list = copy.deepcopy(clone.usemask_list)
			self.pusemask_list = copy.deepcopy(clone.pusemask_list)
			self.useforce      = copy.deepcopy(clone.useforce)
			self.useforce_list = copy.deepcopy(clone.useforce_list)
			self.puseforce_list = copy.deepcopy(clone.puseforce_list)
			self.puse     = copy.deepcopy(clone.puse)
			self.make_defaults_use = copy.deepcopy(clone.make_defaults_use)
			self.pkgprofileuse = copy.deepcopy(clone.pkgprofileuse)
			self.mycpv    = copy.deepcopy(clone.mycpv)
			self._setcpv_args_hash = copy.deepcopy(clone._setcpv_args_hash)

			self.configdict = copy.deepcopy(clone.configdict)
			self.configlist = [
				self.configdict['env.d'],
				self.configdict['pkginternal'],
				self.configdict['globals'],
				self.configdict['defaults'],
				self.configdict['conf'],
				self.configdict['pkg'],
				self.configdict['auto'],
				self.configdict['env'],
			]
			self.lookuplist = self.configlist[:]
			self.lookuplist.reverse()
			self._use_expand_dict = copy.deepcopy(clone._use_expand_dict)
			self.profiles = copy.deepcopy(clone.profiles)
			self.backupenv  = self.configdict["backupenv"]
			self.pusedict   = copy.deepcopy(clone.pusedict)
			self.categories = copy.deepcopy(clone.categories)
			self.pkeywordsdict = copy.deepcopy(clone.pkeywordsdict)
			self._pkeywords_list = copy.deepcopy(clone._pkeywords_list)
			self.pmaskdict = copy.deepcopy(clone.pmaskdict)
			self.punmaskdict = copy.deepcopy(clone.punmaskdict)
			self.prevmaskdict = copy.deepcopy(clone.prevmaskdict)
			self.pprovideddict = copy.deepcopy(clone.pprovideddict)
			self.features = copy.deepcopy(clone.features)

			self._accept_license = copy.deepcopy(clone._accept_license)
			self._plicensedict = copy.deepcopy(clone._plicensedict)
			self._license_groups = copy.deepcopy(clone._license_groups)
			self._accept_properties = copy.deepcopy(clone._accept_properties)
			self._ppropertiesdict = copy.deepcopy(clone._ppropertiesdict)
		else:

			def check_var_directory(varname, var):
				if not os.path.isdir(var):
					writemsg(_("!!! Error: %s='%s' is not a directory. "
						"Please correct this.\n") % (varname, var),
						noiselevel=-1)
					raise portage.exception.DirectoryNotFound(var)

			if config_root is None:
				config_root = "/"

			config_root = normalize_path(os.path.abspath(
				config_root)).rstrip(os.path.sep) + os.path.sep

			check_var_directory("PORTAGE_CONFIGROOT", config_root)

			self.depcachedir = DEPCACHE_PATH

			if not config_profile_path:
				config_profile_path = \
					os.path.join(config_root, PROFILE_PATH)
				if os.path.isdir(config_profile_path):
					self.profile_path = config_profile_path
				else:
					self.profile_path = None
			else:
				self.profile_path = config_profile_path[:]

			if config_incrementals is None:
				self.incrementals = copy.deepcopy(portage.const.INCREMENTALS)
			else:
				self.incrementals = copy.deepcopy(config_incrementals)

			self.module_priority    = ["user","default"]
			self.modules            = {}
			modules_loader = portage.env.loaders.KeyValuePairFileLoader(
				os.path.join(config_root, MODULES_FILE_PATH), None, None)
			modules_dict, modules_errors = modules_loader.load()
			self.modules["user"] = modules_dict
			if self.modules["user"] is None:
				self.modules["user"] = {}
			self.modules["default"] = {
				"portdbapi.metadbmodule": "portage.cache.metadata.database",
				"portdbapi.auxdbmodule":  "portage.cache.flat_hash.database",
			}

			self.usemask=[]
			self.configlist=[]

			# back up our incremental variables:
			self.configdict={}
			self._use_expand_dict = {}
			# configlist will contain: [ env.d, globals, defaults, conf, pkg, auto, backupenv, env ]
			self.configlist.append({})
			self.configdict["env.d"] = self.configlist[-1]

			self.configlist.append({})
			self.configdict["pkginternal"] = self.configlist[-1]

			# The symlink might not exist or might not be a symlink.
			if self.profile_path is None:
				self.profiles = []
			else:
				self.profiles = []
				def addProfile(currentPath):
					parentsFile = os.path.join(currentPath, "parent")
					eapi_file = os.path.join(currentPath, "eapi")
					try:
						eapi = codecs.open(_unicode_encode(eapi_file,
							encoding=_encodings['fs'], errors='strict'),
							mode='r', encoding=_encodings['content'], errors='replace'
							).readline().strip()
					except IOError:
						pass
					else:
						if not eapi_is_supported(eapi):
							raise portage.exception.ParseError(_(
								"Profile contains unsupported "
								"EAPI '%s': '%s'") % \
								(eapi, os.path.realpath(eapi_file),))
					if os.path.exists(parentsFile):
						parents = grabfile(parentsFile)
						if not parents:
							raise portage.exception.ParseError(
								_("Empty parent file: '%s'") % parentsFile)
						for parentPath in parents:
							parentPath = normalize_path(os.path.join(
								currentPath, parentPath))
							if os.path.exists(parentPath):
								addProfile(parentPath)
							else:
								raise portage.exception.ParseError(
									_("Parent '%s' not found: '%s'") %  \
									(parentPath, parentsFile))
					self.profiles.append(currentPath)
				try:
					addProfile(os.path.realpath(self.profile_path))
				except portage.exception.ParseError as e:
					writemsg(_("!!! Unable to parse profile: '%s'\n") % \
						self.profile_path, noiselevel=-1)
					writemsg("!!! ParseError: %s\n" % str(e), noiselevel=-1)
					del e
					self.profiles = []
			if local_config and self.profiles:
				custom_prof = os.path.join(
					config_root, CUSTOM_PROFILE_PATH)
				if os.path.exists(custom_prof):
					self.user_profile_dir = custom_prof
					self.profiles.append(custom_prof)
				del custom_prof

			self.packages_list = [grabfile_package(os.path.join(x, "packages")) for x in self.profiles]
			self.packages      = stack_lists(self.packages_list, incremental=1)
			del self.packages_list
			#self.packages = grab_stacked("packages", self.profiles, grabfile, incremental_lines=1)

			# revmaskdict
			self.prevmaskdict={}
			for x in self.packages:
				# Negative atoms are filtered by the above stack_lists() call.
				if not isinstance(x, dep.Atom):
					x = dep.Atom(x.lstrip('*'))
				self.prevmaskdict.setdefault(x.cp, []).append(x)

			self._pkeywords_list = []
			rawpkeywords = [grabdict_package(
				os.path.join(x, "package.keywords"), recursive=1) \
				for x in self.profiles]
			for pkeyworddict in rawpkeywords:
				cpdict = {}
				for k, v in pkeyworddict.items():
					cpdict.setdefault(k.cp, {})[k] = v
				self._pkeywords_list.append(cpdict)

			# get profile-masked use flags -- INCREMENTAL Child over parent
			self.usemask_list = [grabfile(os.path.join(x, "use.mask"),
				recursive=1) for x in self.profiles]
			self.usemask  = set(stack_lists(
				self.usemask_list, incremental=True))
			use_defs_lists = [grabdict(os.path.join(x, "use.defaults")) for x in self.profiles]
			self.use_defs  = stack_dictlist(use_defs_lists, incremental=True)
			del use_defs_lists

			self.pusemask_list = []
			rawpusemask = [grabdict_package(os.path.join(x, "package.use.mask"),
				recursive=1) for x in self.profiles]
			for pusemaskdict in rawpusemask:
				cpdict = {}
				for k, v in pusemaskdict.items():
					cpdict.setdefault(k.cp, {})[k] = v
				self.pusemask_list.append(cpdict)
			del rawpusemask

			self.pkgprofileuse = []
			rawprofileuse = [grabdict_package(os.path.join(x, "package.use"),
				juststrings=True, recursive=1) for x in self.profiles]
			for rawpusedict in rawprofileuse:
				cpdict = {}
				for k, v in rawpusedict.items():
					cpdict.setdefault(k.cp, {})[k] = v
				self.pkgprofileuse.append(cpdict)
			del rawprofileuse

			self.useforce_list = [grabfile(os.path.join(x, "use.force"),
				recursive=1) for x in self.profiles]
			self.useforce  = set(stack_lists(
				self.useforce_list, incremental=True))

			self.puseforce_list = []
			rawpuseforce = [grabdict_package(
				os.path.join(x, "package.use.force"), recursive=1) \
				for x in self.profiles]
			for rawpusefdict in rawpuseforce:
				cpdict = {}
				for k, v in rawpusefdict.items():
					cpdict.setdefault(k.cp, {})[k] = v
				self.puseforce_list.append(cpdict)
			del rawpuseforce

			make_conf = getconfig(
				os.path.join(config_root, MAKE_CONF_FILE),
				tolerant=tolerant, allow_sourcing=True)
			if make_conf is None:
				make_conf = {}

			# Allow ROOT setting to come from make.conf if it's not overridden
			# by the constructor argument (from the calling environment).
			if target_root is None and "ROOT" in make_conf:
				target_root = make_conf["ROOT"]
				if not target_root.strip():
					target_root = None
			if target_root is None:
				target_root = "/"

			target_root = normalize_path(os.path.abspath(
				target_root)).rstrip(os.path.sep) + os.path.sep

			portage.util.ensure_dirs(target_root)
			check_var_directory("ROOT", target_root)

			# The expand_map is used for variable substitution
			# in getconfig() calls, and the getconfig() calls
			# update expand_map with the value of each variable
			# assignment that occurs. Variable substitution occurs
			# in the following order, which corresponds to the
			# order of appearance in self.lookuplist:
			#
			#   * env.d
			#   * make.globals
			#   * make.defaults
			#   * make.conf
			#
			# Notably absent is "env", since we want to avoid any
			# interaction with the calling environment that might
			# lead to unexpected results.
			expand_map = {}

			env_d = getconfig(os.path.join(target_root, "etc", "profile.env"),
				expand=expand_map)
			# env_d will be None if profile.env doesn't exist.
			if env_d:
				self.configdict["env.d"].update(env_d)
				expand_map.update(env_d)

			# backupenv is used for calculating incremental variables.
			if env is None:
				env = os.environ

			# Avoid potential UnicodeDecodeError exceptions later.
			env_unicode = dict((_unicode_decode(k), _unicode_decode(v))
				for k, v in env.items())

			self.backupenv = env_unicode

			if env_d:
				# Remove duplicate values so they don't override updated
				# profile.env values later (profile.env is reloaded in each
				# call to self.regenerate).
				for k, v in env_d.items():
					try:
						if self.backupenv[k] == v:
							del self.backupenv[k]
					except KeyError:
						pass
				del k, v

			self.configdict["env"] = util.LazyItemsDict(self.backupenv)

			# make.globals should not be relative to config_root
			# because it only contains constants.
			for x in (portage.const.GLOBAL_CONFIG_PATH, "/etc"):
				self.mygcfg = getconfig(os.path.join(x, "make.globals"),
					expand=expand_map)
				if self.mygcfg:
					break

			if self.mygcfg is None:
				self.mygcfg = {}

			for k, v in self._default_globals:
				self.mygcfg.setdefault(k, v)

			self.configlist.append(self.mygcfg)
			self.configdict["globals"]=self.configlist[-1]

			self.make_defaults_use = []
			self.mygcfg = {}
			if self.profiles:
				mygcfg_dlists = [getconfig(os.path.join(x, "make.defaults"),
					expand=expand_map) for x in self.profiles]

				for cfg in mygcfg_dlists:
					if cfg:
						self.make_defaults_use.append(cfg.get("USE", ""))
					else:
						self.make_defaults_use.append("")
				self.mygcfg = stack_dicts(mygcfg_dlists,
					incrementals=portage.const.INCREMENTALS)
				if self.mygcfg is None:
					self.mygcfg = {}
			self.configlist.append(self.mygcfg)
			self.configdict["defaults"]=self.configlist[-1]

			self.mygcfg = getconfig(
				os.path.join(config_root, MAKE_CONF_FILE),
				tolerant=tolerant, allow_sourcing=True, expand=expand_map)
			if self.mygcfg is None:
				self.mygcfg = {}

			# Don't allow the user to override certain variables in make.conf
			profile_only_variables = self.configdict["defaults"].get(
				"PROFILE_ONLY_VARIABLES", "").split()
			for k in profile_only_variables:
				self.mygcfg.pop(k, None)

			self.configlist.append(self.mygcfg)
			self.configdict["conf"]=self.configlist[-1]

			self.configlist.append(util.LazyItemsDict())
			self.configdict["pkg"]=self.configlist[-1]

			#auto-use:
			self.configlist.append({})
			self.configdict["auto"]=self.configlist[-1]

			self.configdict["backupenv"] = self.backupenv

			# Don't allow the user to override certain variables in the env
			for k in profile_only_variables:
				self.backupenv.pop(k, None)

			self.configlist.append(self.configdict["env"])

			# make lookuplist for loading package.*
			self.lookuplist=self.configlist[:]
			self.lookuplist.reverse()

			# Blacklist vars that could interfere with portage internals.
			for blacklisted in self._env_blacklist:
				for cfg in self.lookuplist:
					cfg.pop(blacklisted, None)
				self.backupenv.pop(blacklisted, None)
			del blacklisted, cfg

			self["PORTAGE_CONFIGROOT"] = config_root
			self.backup_changes("PORTAGE_CONFIGROOT")
			self["ROOT"] = target_root
			self.backup_changes("ROOT")

			self.pusedict = {}
			self.pkeywordsdict = {}
			self._plicensedict = {}
			self._ppropertiesdict = {}
			self.punmaskdict = {}
			abs_user_config = os.path.join(config_root, USER_CONFIG_PATH)

			# locations for "categories" and "arch.list" files
			locations = [os.path.join(self["PORTDIR"], "profiles")]
			pmask_locations = [os.path.join(self["PORTDIR"], "profiles")]
			pmask_locations.extend(self.profiles)

			""" repoman controls PORTDIR_OVERLAY via the environment, so no
			special cases are needed here."""
			overlay_profiles = []
			for ov in self["PORTDIR_OVERLAY"].split():
				ov = normalize_path(ov)
				profiles_dir = os.path.join(ov, "profiles")
				if os.path.isdir(profiles_dir):
					overlay_profiles.append(profiles_dir)
			locations += overlay_profiles
			
			pmask_locations.extend(overlay_profiles)

			if local_config:
				locations.append(abs_user_config)
				pmask_locations.append(abs_user_config)
				pusedict = grabdict_package(
					os.path.join(abs_user_config, "package.use"), recursive=1)
				for k, v in pusedict.items():
					self.pusedict.setdefault(k.cp, {})[k] = v

				#package.keywords
				pkgdict = grabdict_package(
					os.path.join(abs_user_config, "package.keywords"),
					recursive=1)
				for k, v in pkgdict.items():
					# default to ~arch if no specific keyword is given
					if not v:
						mykeywordlist = []
						if self.configdict["defaults"] and \
							"ACCEPT_KEYWORDS" in self.configdict["defaults"]:
							groups = self.configdict["defaults"]["ACCEPT_KEYWORDS"].split()
						else:
							groups = []
						for keyword in groups:
							if not keyword[0] in "~-":
								mykeywordlist.append("~"+keyword)
						v = mykeywordlist
					self.pkeywordsdict.setdefault(k.cp, {})[k] = v

				#package.license
				licdict = grabdict_package(os.path.join(
					abs_user_config, "package.license"), recursive=1)
				for k, v in licdict.items():
					cp = k.cp
					cp_dict = self._plicensedict.get(cp)
					if not cp_dict:
						cp_dict = {}
						self._plicensedict[cp] = cp_dict
					cp_dict[k] = self.expandLicenseTokens(v)

				#package.properties
				propdict = grabdict_package(os.path.join(
					abs_user_config, "package.properties"), recursive=1)
				for k, v in propdict.items():
					cp = k.cp
					cp_dict = self._ppropertiesdict.get(cp)
					if not cp_dict:
						cp_dict = {}
						self._ppropertiesdict[cp] = cp_dict
					cp_dict[k] = v

				self._local_repo_configs = {}
				self._local_repo_conf_path = \
					os.path.join(abs_user_config, 'repos.conf')
				try:
					from configparser import SafeConfigParser, ParsingError
				except ImportError:
					from ConfigParser import SafeConfigParser, ParsingError
				repo_conf_parser = SafeConfigParser()
				try:
					repo_conf_parser.readfp(
						codecs.open(
						_unicode_encode(self._local_repo_conf_path,
						encoding=_encodings['fs'], errors='strict'),
						mode='r', encoding=_encodings['content'], errors='replace')
					)
				except EnvironmentError as e:
					if e.errno != errno.ENOENT:
						raise
					del e
				except ParsingError as e:
					portage.util.writemsg_level(
						_("!!! Error parsing '%s': %s\n")  % \
						(self._local_repo_conf_path, e),
						level=logging.ERROR, noiselevel=-1)
					del e
				else:
					repo_defaults = repo_conf_parser.defaults()
					if repo_defaults:
						self._local_repo_configs['DEFAULT'] = \
							_local_repo_config('DEFAULT', repo_defaults)
					for repo_name in repo_conf_parser.sections():
						repo_opts = repo_defaults.copy()
						for opt_name in repo_conf_parser.options(repo_name):
							repo_opts[opt_name] = \
								repo_conf_parser.get(repo_name, opt_name)
						self._local_repo_configs[repo_name] = \
							_local_repo_config(repo_name, repo_opts)

			#getting categories from an external file now
			categories = [grabfile(os.path.join(x, "categories")) for x in locations]
			self.categories = tuple(sorted(
				stack_lists(categories, incremental=1)))
			del categories

			archlist = [grabfile(os.path.join(x, "arch.list")) for x in locations]
			archlist = stack_lists(archlist, incremental=1)
			self.configdict["conf"]["PORTAGE_ARCHLIST"] = " ".join(archlist)

			# package.mask and package.unmask
			pkgmasklines = []
			pkgunmasklines = []
			for x in pmask_locations:
				pkgmasklines.append(grabfile_package(
					os.path.join(x, "package.mask"), recursive=1))
				pkgunmasklines.append(grabfile_package(
					os.path.join(x, "package.unmask"), recursive=1))
			pkgmasklines = stack_lists(pkgmasklines, incremental=1)
			pkgunmasklines = stack_lists(pkgunmasklines, incremental=1)

			self.pmaskdict = {}
			for x in pkgmasklines:
				self.pmaskdict.setdefault(x.cp, []).append(x)

			for x in pkgunmasklines:
				self.punmaskdict.setdefault(x.cp, []).append(x)

			pkgprovidedlines = [grabfile(os.path.join(x, "package.provided"), recursive=1) for x in self.profiles]
			pkgprovidedlines = stack_lists(pkgprovidedlines, incremental=1)
			has_invalid_data = False
			for x in range(len(pkgprovidedlines)-1, -1, -1):
				myline = pkgprovidedlines[x]
				if not isvalidatom("=" + myline):
					writemsg(_("Invalid package name in package.provided: %s\n") % \
						myline, noiselevel=-1)
					has_invalid_data = True
					del pkgprovidedlines[x]
					continue
				cpvr = catpkgsplit(pkgprovidedlines[x])
				if not cpvr or cpvr[0] == "null":
					writemsg(_("Invalid package name in package.provided: ")+pkgprovidedlines[x]+"\n",
						noiselevel=-1)
					has_invalid_data = True
					del pkgprovidedlines[x]
					continue
				if cpvr[0] == "virtual":
					writemsg(_("Virtual package in package.provided: %s\n") % \
						myline, noiselevel=-1)
					has_invalid_data = True
					del pkgprovidedlines[x]
					continue
			if has_invalid_data:
				writemsg(_("See portage(5) for correct package.provided usage.\n"),
					noiselevel=-1)
			self.pprovideddict = {}
			for x in pkgprovidedlines:
				cpv=catpkgsplit(x)
				if not x:
					continue
				mycatpkg = cpv_getkey(x)
				if mycatpkg in self.pprovideddict:
					self.pprovideddict[mycatpkg].append(x)
				else:
					self.pprovideddict[mycatpkg]=[x]

			# parse licensegroups
			for x in locations:
				self._license_groups.update(
					grabdict(os.path.join(x, "license_groups")))

			# reasonable defaults; this is important as without USE_ORDER,
			# USE will always be "" (nothing set)!
			if "USE_ORDER" not in self:
				self.backupenv["USE_ORDER"] = "env:pkg:conf:defaults:pkginternal:env.d"

			self["PORTAGE_GID"] = str(portage_gid)
			self.backup_changes("PORTAGE_GID")

			if self.get("PORTAGE_DEPCACHEDIR", None):
				self.depcachedir = self["PORTAGE_DEPCACHEDIR"]
			self["PORTAGE_DEPCACHEDIR"] = self.depcachedir
			self.backup_changes("PORTAGE_DEPCACHEDIR")

			overlays = self.get("PORTDIR_OVERLAY","").split()
			if overlays:
				new_ov = []
				for ov in overlays:
					ov = normalize_path(ov)
					if os.path.isdir(ov):
						new_ov.append(ov)
					else:
						writemsg(_("!!! Invalid PORTDIR_OVERLAY"
							" (not a dir): '%s'\n") % ov, noiselevel=-1)
				self["PORTDIR_OVERLAY"] = " ".join(new_ov)
				self.backup_changes("PORTDIR_OVERLAY")

			if "CBUILD" not in self and "CHOST" in self:
				self["CBUILD"] = self["CHOST"]
				self.backup_changes("CBUILD")

			self["PORTAGE_BIN_PATH"] = PORTAGE_BIN_PATH
			self.backup_changes("PORTAGE_BIN_PATH")
			self["PORTAGE_PYM_PATH"] = PORTAGE_PYM_PATH
			self.backup_changes("PORTAGE_PYM_PATH")

			for var in ("PORTAGE_INST_UID", "PORTAGE_INST_GID"):
				try:
					self[var] = str(int(self.get(var, "0")))
				except ValueError:
					writemsg(_("!!! %s='%s' is not a valid integer.  "
						"Falling back to '0'.\n") % (var, self[var]),
						noiselevel=-1)
					self[var] = "0"
				self.backup_changes(var)

			# initialize self.features
			self.regenerate()

			if not portage.process.sandbox_capable and \
				("sandbox" in self.features or "usersandbox" in self.features):
				if self.profile_path is not None and \
					os.path.realpath(self.profile_path) == \
					os.path.realpath(os.path.join(config_root, PROFILE_PATH)):
					""" Don't show this warning when running repoman and the
					sandbox feature came from a profile that doesn't belong to
					the user."""
					writemsg(colorize("BAD", _("!!! Problem with sandbox"
						" binary. Disabling...\n\n")), noiselevel=-1)
				if "sandbox" in self.features:
					self.features.remove("sandbox")
				if "usersandbox" in self.features:
					self.features.remove("usersandbox")

			if bsd_chflags:
				self.features.add('chflags')

			self["FEATURES"] = " ".join(sorted(self.features))
			self.backup_changes("FEATURES")
			global _glep_55_enabled, _validate_cache_for_unsupported_eapis
			if 'parse-eapi-ebuild-head' in self.features:
				_validate_cache_for_unsupported_eapis = False
			if 'parse-eapi-glep-55' in self.features:
				_validate_cache_for_unsupported_eapis = False
				_glep_55_enabled = True

			self._init_dirs()

		for k in self._case_insensitive_vars:
			if k in self:
				self[k] = self[k].lower()
				self.backup_changes(k)

		if mycpv:
			self.setcpv(mycpv)

	def _init_dirs(self):
		"""
		Create a few directories that are critical to portage operation
		"""
		if not os.access(self["ROOT"], os.W_OK):
			return

		#                                gid, mode, mask, preserve_perms
		dir_mode_map = {
			"tmp"             : (         -1, 0o1777,  0,  True),
			"var/tmp"         : (         -1, 0o1777,  0,  True),
			PRIVATE_PATH      : (portage_gid, 0o2750, 0o2, False),
			CACHE_PATH        : (portage_gid,  0o755, 0o2, False)
		}

		for mypath, (gid, mode, modemask, preserve_perms) \
			in dir_mode_map.items():
			mydir = os.path.join(self["ROOT"], mypath)
			if preserve_perms and os.path.isdir(mydir):
				# Only adjust permissions on some directories if
				# they don't exist yet. This gives freedom to the
				# user to adjust permissions to suit their taste.
				continue
			try:
				portage.util.ensure_dirs(mydir, gid=gid, mode=mode, mask=modemask)
			except portage.exception.PortageException as e:
				writemsg(_("!!! Directory initialization failed: '%s'\n") % mydir,
					noiselevel=-1)
				writemsg("!!! %s\n" % str(e),
					noiselevel=-1)

	def expandLicenseTokens(self, tokens):
		""" Take a token from ACCEPT_LICENSE or package.license and expand it
		if it's a group token (indicated by @) or just return it if it's not a
		group.  If a group is negated then negate all group elements."""
		expanded_tokens = []
		for x in tokens:
			expanded_tokens.extend(self._expandLicenseToken(x, None))
		return expanded_tokens

	def _expandLicenseToken(self, token, traversed_groups):
		negate = False
		rValue = []
		if token.startswith("-"):
			negate = True
			license_name = token[1:]
		else:
			license_name = token
		if not license_name.startswith("@"):
			rValue.append(token)
			return rValue
		group_name = license_name[1:]
		if not traversed_groups:
			traversed_groups = set()
		license_group = self._license_groups.get(group_name)
		if group_name in traversed_groups:
			writemsg(_("Circular license group reference"
				" detected in '%s'\n") % group_name, noiselevel=-1)
			rValue.append("@"+group_name)
		elif license_group:
			traversed_groups.add(group_name)
			for l in license_group:
				if l.startswith("-"):
					writemsg(_("Skipping invalid element %s"
						" in license group '%s'\n") % (l, group_name),
						noiselevel=-1)
				else:
					rValue.extend(self._expandLicenseToken(l, traversed_groups))
		else:
			if self._license_groups and \
				group_name not in self._undef_lic_groups:
				self._undef_lic_groups.add(group_name)
				writemsg(_("Undefined license group '%s'\n") % group_name,
					noiselevel=-1)
			rValue.append("@"+group_name)
		if negate:
			rValue = ["-" + token for token in rValue]
		return rValue

	def validate(self):
		"""Validate miscellaneous settings and display warnings if necessary.
		(This code was previously in the global scope of portage.py)"""

		groups = self["ACCEPT_KEYWORDS"].split()
		archlist = self.archlist()
		if not archlist:
			writemsg(_("--- 'profiles/arch.list' is empty or "
				"not available. Empty portage tree?\n"), noiselevel=1)
		else:
			for group in groups:
				if group not in archlist and \
					not (group.startswith("-") and group[1:] in archlist) and \
					group not in ("*", "~*", "**"):
					writemsg(_("!!! INVALID ACCEPT_KEYWORDS: %s\n") % str(group),
						noiselevel=-1)

		abs_profile_path = os.path.join(self["PORTAGE_CONFIGROOT"],
			PROFILE_PATH)
		if not self.profile_path or (not os.path.islink(abs_profile_path) and \
			not os.path.exists(os.path.join(abs_profile_path, "parent")) and \
			os.path.exists(os.path.join(self["PORTDIR"], "profiles"))):
			writemsg(_("\a\n\n!!! %s is not a symlink and will probably prevent most merges.\n") % abs_profile_path,
				noiselevel=-1)
			writemsg(_("!!! It should point into a profile within %s/profiles/\n") % self["PORTDIR"])
			writemsg(_("!!! (You can safely ignore this message when syncing. It's harmless.)\n\n\n"))

		abs_user_virtuals = os.path.join(self["PORTAGE_CONFIGROOT"],
			USER_VIRTUALS_FILE)
		if os.path.exists(abs_user_virtuals):
			writemsg("\n!!! /etc/portage/virtuals is deprecated in favor of\n")
			writemsg("!!! /etc/portage/profile/virtuals. Please move it to\n")
			writemsg("!!! this new location.\n\n")

		if "fakeroot" in self.features and \
			not portage.process.fakeroot_capable:
			writemsg(_("!!! FEATURES=fakeroot is enabled, but the "
				"fakeroot binary is not installed.\n"), noiselevel=-1)

	def loadVirtuals(self,root):
		"""Not currently used by portage."""
		writemsg("DEPRECATED: portage.config.loadVirtuals\n")
		self.getvirtuals(root)

	def load_best_module(self,property_string):
		best_mod = best_from_dict(property_string,self.modules,self.module_priority)
		mod = None
		try:
			mod = load_mod(best_mod)
		except ImportError:
			if best_mod.startswith("cache."):
				best_mod = "portage." + best_mod
				try:
					mod = load_mod(best_mod)
				except ImportError:
					pass
		if mod is None:
			raise
		return mod

	def lock(self):
		self.locked = 1

	def unlock(self):
		self.locked = 0

	def modifying(self):
		if self.locked:
			raise Exception(_("Configuration is locked."))

	def backup_changes(self,key=None):
		self.modifying()
		if key and key in self.configdict["env"]:
			self.backupenv[key] = copy.deepcopy(self.configdict["env"][key])
		else:
			raise KeyError(_("No such key defined in environment: %s") % key)

	def reset(self,keeping_pkg=0,use_cache=1):
		"""
		Restore environment from self.backupenv, call self.regenerate()
		@param keeping_pkg: Should we keep the set_cpv() data or delete it.
		@type keeping_pkg: Boolean
		@param use_cache: Should self.regenerate use the cache or not
		@type use_cache: Boolean
		@rype: None
		"""
		self.modifying()
		self.configdict["env"].clear()
		self.configdict["env"].update(self.backupenv)

		self.modifiedkeys = []
		if not keeping_pkg:
			self.mycpv = None
			self.puse = ""
			self.configdict["pkg"].clear()
			self.configdict["pkginternal"].clear()
			self.configdict["defaults"]["USE"] = \
				" ".join(self.make_defaults_use)
			self.usemask  = set(stack_lists(
				self.usemask_list, incremental=True))
			self.useforce  = set(stack_lists(
				self.useforce_list, incremental=True))
		self.regenerate(use_cache=use_cache)

	def load_infodir(self,infodir):
		warnings.warn("portage.config.load_infodir() is deprecated",
			DeprecationWarning)
		return 1

	class _lazy_vars(object):

		__slots__ = ('built_use', 'settings', 'values')

		def __init__(self, built_use, settings):
			self.built_use = built_use
			self.settings = settings
			self.values = None

		def __getitem__(self, k):
			if self.values is None:
				self.values = self._init_values()
			return self.values[k]

		def _init_values(self):
			values = {}
			settings = self.settings
			use = self.built_use
			if use is None:
				use = frozenset(settings['PORTAGE_USE'].split())
			values['ACCEPT_LICENSE'] = self._accept_license(use, settings)
			values['PORTAGE_RESTRICT'] = self._restrict(use, settings)
			return values

		def _accept_license(self, use, settings):
			"""
			Generate a pruned version of ACCEPT_LICENSE, by intersection with
			LICENSE. This is required since otherwise ACCEPT_LICENSE might be
			too big (bigger than ARG_MAX), causing execve() calls to fail with
			E2BIG errors as in bug #262647.
			"""
			try:
				licenses = set(flatten(
					dep.use_reduce(dep.paren_reduce(
					settings['LICENSE']),
					uselist=use)))
			except exception.InvalidDependString:
				licenses = set()
			licenses.discard('||')
			if settings._accept_license:
				acceptable_licenses = set()
				for x in settings._accept_license:
					if x == '*':
						acceptable_licenses.update(licenses)
					elif x == '-*':
						acceptable_licenses.clear()
					elif x[:1] == '-':
						acceptable_licenses.discard(x[1:])
					elif x in licenses:
						acceptable_licenses.add(x)

				licenses = acceptable_licenses
			return ' '.join(sorted(licenses))

		def _restrict(self, use, settings):
			try:
				restrict = set(flatten(
					dep.use_reduce(dep.paren_reduce(
					settings['RESTRICT']),
					uselist=use)))
			except exception.InvalidDependString:
				restrict = set()
			return ' '.join(sorted(restrict))

	class _lazy_use_expand(object):
		"""
		Lazily evaluate USE_EXPAND variables since they are only needed when
		an ebuild shell is spawned. Variables values are made consistent with
		the previously calculated USE settings.
		"""

		def __init__(self, use, usemask, iuse_implicit,
			use_expand_split, use_expand_dict):
			self._use = use
			self._usemask = usemask
			self._iuse_implicit = iuse_implicit
			self._use_expand_split = use_expand_split
			self._use_expand_dict = use_expand_dict

		def __getitem__(self, key):
			prefix = key.lower() + '_'
			prefix_len = len(prefix)
			expand_flags = set( x[prefix_len:] for x in self._use \
				if x[:prefix_len] == prefix )
			var_split = self._use_expand_dict.get(key, '').split()
			# Preserve the order of var_split because it can matter for things
			# like LINGUAS.
			var_split = [ x for x in var_split if x in expand_flags ]
			var_split.extend(expand_flags.difference(var_split))
			has_wildcard = '*' in expand_flags
			if has_wildcard:
				var_split = [ x for x in var_split if x != "*" ]
			has_iuse = set()
			for x in self._iuse_implicit:
				if x[:prefix_len] == prefix:
					has_iuse.add(x[prefix_len:])
			if has_wildcard:
				# * means to enable everything in IUSE that's not masked
				if has_iuse:
					usemask = self._usemask
					for suffix in has_iuse:
						x = prefix + suffix
						if x not in usemask:
							if suffix not in expand_flags:
								var_split.append(suffix)
				else:
					# If there is a wildcard and no matching flags in IUSE then
					# LINGUAS should be unset so that all .mo files are
					# installed.
					var_split = []
			# Make the flags unique and filter them according to IUSE.
			# Also, continue to preserve order for things like LINGUAS
			# and filter any duplicates that variable may contain.
			filtered_var_split = []
			remaining = has_iuse.intersection(var_split)
			for x in var_split:
				if x in remaining:
					remaining.remove(x)
					filtered_var_split.append(x)
			var_split = filtered_var_split

			if var_split:
				value = ' '.join(var_split)
			else:
				# Don't export empty USE_EXPAND vars unless the user config
				# exports them as empty.  This is required for vars such as
				# LINGUAS, where unset and empty have different meanings.
				if has_wildcard:
					# ebuild.sh will see this and unset the variable so
					# that things like LINGUAS work properly
					value = '*'
				else:
					if has_iuse:
						value = ''
					else:
						# It's not in IUSE, so just allow the variable content
						# to pass through if it is defined somewhere.  This
						# allows packages that support LINGUAS but don't
						# declare it in IUSE to use the variable outside of the
						# USE_EXPAND context.
						value = None

			return value

	def setcpv(self, mycpv, use_cache=1, mydb=None):
		"""
		Load a particular CPV into the config, this lets us see the
		Default USE flags for a particular ebuild as well as the USE
		flags from package.use.

		@param mycpv: A cpv to load
		@type mycpv: string
		@param use_cache: Enables caching
		@type use_cache: Boolean
		@param mydb: a dbapi instance that supports aux_get with the IUSE key.
		@type mydb: dbapi or derivative.
		@rtype: None
		"""

		self.modifying()

		pkg = None
		built_use = None
		if not isinstance(mycpv, basestring):
			pkg = mycpv
			mycpv = pkg.cpv
			mydb = pkg.metadata
			args_hash = (mycpv, id(pkg))
			if pkg.built:
				built_use = pkg.use.enabled
		else:
			args_hash = (mycpv, id(mydb))

		if args_hash == self._setcpv_args_hash:
			return
		self._setcpv_args_hash = args_hash

		has_changed = False
		self.mycpv = mycpv
		cat, pf = catsplit(mycpv)
		cp = dep_getkey(mycpv)
		cpv_slot = self.mycpv
		pkginternaluse = ""
		iuse = ""
		pkg_configdict = self.configdict["pkg"]
		previous_iuse = pkg_configdict.get("IUSE")

		aux_keys = self._setcpv_aux_keys

		# Discard any existing metadata from the previous package, but
		# preserve things like USE_EXPAND values and PORTAGE_USE which
		# might be reused.
		for k in aux_keys:
			pkg_configdict.pop(k, None)

		pkg_configdict["CATEGORY"] = cat
		pkg_configdict["PF"] = pf
		if mydb:
			if not hasattr(mydb, "aux_get"):
				for k in aux_keys:
					if k in mydb:
						# Make these lazy, since __getitem__ triggers
						# evaluation of USE conditionals which can't
						# occur until PORTAGE_USE is calculated below.
						pkg_configdict.addLazySingleton(k,
							mydb.__getitem__, k)
			else:
				for k, v in zip(aux_keys, mydb.aux_get(self.mycpv, aux_keys)):
					pkg_configdict[k] = v
			repository = pkg_configdict.pop("repository", None)
			if repository is not None:
				pkg_configdict["PORTAGE_REPO_NAME"] = repository
			slot = pkg_configdict["SLOT"]
			iuse = pkg_configdict["IUSE"]
			if pkg is None:
				cpv_slot = "%s:%s" % (self.mycpv, slot)
			else:
				cpv_slot = pkg
			pkginternaluse = []
			for x in iuse.split():
				if x.startswith("+"):
					pkginternaluse.append(x[1:])
				elif x.startswith("-"):
					pkginternaluse.append(x)
			pkginternaluse = " ".join(pkginternaluse)
		if pkginternaluse != self.configdict["pkginternal"].get("USE", ""):
			self.configdict["pkginternal"]["USE"] = pkginternaluse
			has_changed = True

		defaults = []
		pos = 0
		for i, pkgprofileuse_dict in enumerate(self.pkgprofileuse):
			cpdict = pkgprofileuse_dict.get(cp)
			if cpdict:
				keys = list(cpdict)
				while keys:
					bestmatch = best_match_to_list(cpv_slot, keys)
					if bestmatch:
						keys.remove(bestmatch)
						defaults.insert(pos, cpdict[bestmatch])
					else:
						break
				del keys
			if self.make_defaults_use[i]:
				defaults.insert(pos, self.make_defaults_use[i])
			pos = len(defaults)
		defaults = " ".join(defaults)
		if defaults != self.configdict["defaults"].get("USE",""):
			self.configdict["defaults"]["USE"] = defaults
			has_changed = True

		useforce = self._getUseForce(cpv_slot)
		if useforce != self.useforce:
			self.useforce = useforce
			has_changed = True

		usemask = self._getUseMask(cpv_slot)
		if usemask != self.usemask:
			self.usemask = usemask
			has_changed = True
		oldpuse = self.puse
		self.puse = ""
		cpdict = self.pusedict.get(cp)
		if cpdict:
			keys = list(cpdict)
			while keys:
				self.pusekey = best_match_to_list(cpv_slot, keys)
				if self.pusekey:
					keys.remove(self.pusekey)
					self.puse = (" ".join(cpdict[self.pusekey])) + " " + self.puse
				else:
					break
			del keys
		if oldpuse != self.puse:
			has_changed = True
		self.configdict["pkg"]["PKGUSE"] = self.puse[:] # For saving to PUSE file
		self.configdict["pkg"]["USE"]    = self.puse[:] # this gets appended to USE

		if has_changed:
			self.reset(keeping_pkg=1,use_cache=use_cache)

		# Ensure that "pkg" values are always preferred over "env" values.
		# This must occur _after_ the above reset() call, since reset()
		# copies values from self.backupenv.
		env_configdict = self.configdict['env']
		for k in pkg_configdict:
			if k != 'USE':
				env_configdict.pop(k, None)

		lazy_vars = self._lazy_vars(built_use, self)
		env_configdict.addLazySingleton('ACCEPT_LICENSE',
			lazy_vars.__getitem__, 'ACCEPT_LICENSE')
		env_configdict.addLazySingleton('PORTAGE_RESTRICT',
			lazy_vars.__getitem__, 'PORTAGE_RESTRICT')

		# If reset() has not been called, it's safe to return
		# early if IUSE has not changed.
		if not has_changed and previous_iuse == iuse:
			return

		# Filter out USE flags that aren't part of IUSE. This has to
		# be done for every setcpv() call since practically every
		# package has different IUSE.
		use = set(self["USE"].split())
		iuse_implicit = self._get_implicit_iuse()
		iuse_implicit.update(x.lstrip("+-") for x in iuse.split())

		# PORTAGE_IUSE is not always needed so it's lazily evaluated.
		self.configdict["pkg"].addLazySingleton(
			"PORTAGE_IUSE", _lazy_iuse_regex, iuse_implicit)

		ebuild_force_test = self.get("EBUILD_FORCE_TEST") == "1"
		if ebuild_force_test and \
			not hasattr(self, "_ebuild_force_test_msg_shown"):
				self._ebuild_force_test_msg_shown = True
				writemsg(_("Forcing test.\n"), noiselevel=-1)
		if "test" in self.features and "test" in iuse_implicit:
			if "test" in self.usemask and not ebuild_force_test:
				# "test" is in IUSE and USE=test is masked, so execution
				# of src_test() probably is not reliable. Therefore,
				# temporarily disable FEATURES=test just for this package.
				self["FEATURES"] = " ".join(x for x in self.features \
					if x != "test")
				use.discard("test")
			else:
				use.add("test")
				if ebuild_force_test:
					self.usemask.discard("test")

		# Allow _* flags from USE_EXPAND wildcards to pass through here.
		use.difference_update([x for x in use \
			if x not in iuse_implicit and x[-2:] != '_*'])

		# Use the calculated USE flags to regenerate the USE_EXPAND flags so
		# that they are consistent. For optimal performance, use slice
		# comparison instead of startswith().
		use_expand_split = set(x.lower() for \
			x in self.get('USE_EXPAND', '').split())
		lazy_use_expand = self._lazy_use_expand(use, self.usemask,
			iuse_implicit, use_expand_split, self._use_expand_dict)

		use_expand_iuses = {}
		for x in iuse_implicit:
			x_split = x.split('_')
			if len(x_split) == 1:
				continue
			for i in range(len(x_split) - 1):
				k = '_'.join(x_split[:i+1])
				if k in use_expand_split:
					v = use_expand_iuses.get(k)
					if v is None:
						v = set()
						use_expand_iuses[k] = v
					v.add(x)
					break

		# If it's not in IUSE, variable content is allowed
		# to pass through if it is defined somewhere.  This
		# allows packages that support LINGUAS but don't
		# declare it in IUSE to use the variable outside of the
		# USE_EXPAND context.
		for k, use_expand_iuse in use_expand_iuses.items():
			if k + '_*' in use:
				use.update( x for x in use_expand_iuse if x not in usemask )
			k = k.upper()
			self.configdict['env'].addLazySingleton(k,
				lazy_use_expand.__getitem__, k)

		# Filtered for the ebuild environment. Store this in a separate
		# attribute since we still want to be able to see global USE
		# settings for things like emerge --info.

		self.configdict["pkg"]["PORTAGE_USE"] = \
			" ".join(sorted(x for x in use if x[-2:] != '_*'))

	def _get_implicit_iuse(self):
		"""
		Some flags are considered to
		be implicit members of IUSE:
		  * Flags derived from ARCH
		  * Flags derived from USE_EXPAND_HIDDEN variables
		  * Masked flags, such as those from {,package}use.mask
		  * Forced flags, such as those from {,package}use.force
		  * build and bootstrap flags used by bootstrap.sh
		"""
		iuse_implicit = set()
		# Flags derived from ARCH.
		arch = self.configdict["defaults"].get("ARCH")
		if arch:
			iuse_implicit.add(arch)
		iuse_implicit.update(self.get("PORTAGE_ARCHLIST", "").split())

		# Flags derived from USE_EXPAND_HIDDEN variables
		# such as ELIBC, KERNEL, and USERLAND.
		use_expand_hidden = self.get("USE_EXPAND_HIDDEN", "").split()
		for x in use_expand_hidden:
			iuse_implicit.add(x.lower() + "_.*")

		# Flags that have been masked or forced.
		iuse_implicit.update(self.usemask)
		iuse_implicit.update(self.useforce)

		# build and bootstrap flags used by bootstrap.sh
		iuse_implicit.add("build")
		iuse_implicit.add("bootstrap")
		return iuse_implicit

	def _getUseMask(self, pkg):
		cp = getattr(pkg, "cp", None)
		if cp is None:
			cp = dep_getkey(pkg)
		usemask = []
		pos = 0
		for i, pusemask_dict in enumerate(self.pusemask_list):
			cpdict = pusemask_dict.get(cp)
			if cpdict:
				keys = list(cpdict)
				while keys:
					best_match = best_match_to_list(pkg, keys)
					if best_match:
						keys.remove(best_match)
						usemask.insert(pos, cpdict[best_match])
					else:
						break
				del keys
			if self.usemask_list[i]:
				usemask.insert(pos, self.usemask_list[i])
			pos = len(usemask)
		return set(stack_lists(usemask, incremental=True))

	def _getUseForce(self, pkg):
		cp = getattr(pkg, "cp", None)
		if cp is None:
			cp = dep_getkey(pkg)
		useforce = []
		pos = 0
		for i, puseforce_dict in enumerate(self.puseforce_list):
			cpdict = puseforce_dict.get(cp)
			if cpdict:
				keys = list(cpdict)
				while keys:
					best_match = best_match_to_list(pkg, keys)
					if best_match:
						keys.remove(best_match)
						useforce.insert(pos, cpdict[best_match])
					else:
						break
				del keys
			if self.useforce_list[i]:
				useforce.insert(pos, self.useforce_list[i])
			pos = len(useforce)
		return set(stack_lists(useforce, incremental=True))

	def _getMaskAtom(self, cpv, metadata):
		"""
		Take a package and return a matching package.mask atom, or None if no
		such atom exists or it has been cancelled by package.unmask. PROVIDE
		is not checked, so atoms will not be found for old-style virtuals.

		@param cpv: The package name
		@type cpv: String
		@param metadata: A dictionary of raw package metadata
		@type metadata: dict
		@rtype: String
		@return: An matching atom string or None if one is not found.
		"""

		cp = cpv_getkey(cpv)
		mask_atoms = self.pmaskdict.get(cp)
		if mask_atoms:
			pkg_list = ["%s:%s" % (cpv, metadata["SLOT"])]
			unmask_atoms = self.punmaskdict.get(cp)
			for x in mask_atoms:
				if not match_from_list(x, pkg_list):
					continue
				if unmask_atoms:
					for y in unmask_atoms:
						if match_from_list(y, pkg_list):
							return None
				return x
		return None

	def _getProfileMaskAtom(self, cpv, metadata):
		"""
		Take a package and return a matching profile atom, or None if no
		such atom exists. Note that a profile atom may or may not have a "*"
		prefix. PROVIDE is not checked, so atoms will not be found for
		old-style virtuals.

		@param cpv: The package name
		@type cpv: String
		@param metadata: A dictionary of raw package metadata
		@type metadata: dict
		@rtype: String
		@return: An matching profile atom string or None if one is not found.
		"""

		cp = cpv_getkey(cpv)
		profile_atoms = self.prevmaskdict.get(cp)
		if profile_atoms:
			pkg_list = ["%s:%s" % (cpv, metadata["SLOT"])]
			for x in profile_atoms:
				if match_from_list(x, pkg_list):
					continue
				return x
		return None

	def _getKeywords(self, cpv, metadata):
		cp = cpv_getkey(cpv)
		pkg = "%s:%s" % (cpv, metadata["SLOT"])
		keywords = [[x for x in metadata["KEYWORDS"].split() if x != "-*"]]
		pos = len(keywords)
		for pkeywords_dict in self._pkeywords_list:
			cpdict = pkeywords_dict.get(cp)
			if cpdict:
				keys = list(cpdict)
				while keys:
					best_match = best_match_to_list(pkg, keys)
					if best_match:
						keys.remove(best_match)
						keywords.insert(pos, cpdict[best_match])
					else:
						break
			pos = len(keywords)
		return stack_lists(keywords, incremental=True)

	def _getMissingKeywords(self, cpv, metadata):
		"""
		Take a package and return a list of any KEYWORDS that the user may
		may need to accept for the given package. If the KEYWORDS are empty
		and the the ** keyword has not been accepted, the returned list will
		contain ** alone (in order to distiguish from the case of "none
		missing").

		@param cpv: The package name (for package.keywords support)
		@type cpv: String
		@param metadata: A dictionary of raw package metadata
		@type metadata: dict
		@rtype: List
		@return: A list of KEYWORDS that have not been accepted.
		"""

		# Hack: Need to check the env directly here as otherwise stacking 
		# doesn't work properly as negative values are lost in the config
		# object (bug #139600)
		egroups = self.configdict["backupenv"].get(
			"ACCEPT_KEYWORDS", "").split()
		mygroups = self._getKeywords(cpv, metadata)
		# Repoman may modify this attribute as necessary.
		pgroups = self["ACCEPT_KEYWORDS"].split()
		match=0
		cp = cpv_getkey(cpv)
		pkgdict = self.pkeywordsdict.get(cp)
		matches = False
		if pkgdict:
			cpv_slot_list = ["%s:%s" % (cpv, metadata["SLOT"])]
			for atom, pkgkeywords in pkgdict.items():
				if match_from_list(atom, cpv_slot_list):
					matches = True
					pgroups.extend(pkgkeywords)
		if matches or egroups:
			pgroups.extend(egroups)
			inc_pgroups = set()
			for x in pgroups:
				if x.startswith("-"):
					if x == "-*":
						inc_pgroups.clear()
					else:
						inc_pgroups.discard(x[1:])
				else:
					inc_pgroups.add(x)
			pgroups = inc_pgroups
			del inc_pgroups
		hasstable = False
		hastesting = False
		for gp in mygroups:
			if gp == "*" or (gp == "-*" and len(mygroups) == 1):
				writemsg(_("--- WARNING: Package '%(cpv)s' uses"
					" '%(keyword)s' keyword.\n") % {"cpv": cpv, "keyword": gp}, noiselevel=-1)
				if gp == "*":
					match = 1
					break
			elif gp in pgroups:
				match=1
				break
			elif gp.startswith("~"):
				hastesting = True
			elif not gp.startswith("-"):
				hasstable = True
		if not match and \
			((hastesting and "~*" in pgroups) or \
			(hasstable and "*" in pgroups) or "**" in pgroups):
			match=1
		if match:
			missing = []
		else:
			if not mygroups:
				# If KEYWORDS is empty then we still have to return something
				# in order to distiguish from the case of "none missing".
				mygroups.append("**")
			missing = mygroups
		return missing

	def _getMissingLicenses(self, cpv, metadata):
		"""
		Take a LICENSE string and return a list any licenses that the user may
		may need to accept for the given package.  The returned list will not
		contain any licenses that have already been accepted.  This method
		can throw an InvalidDependString exception.

		@param cpv: The package name (for package.license support)
		@type cpv: String
		@param metadata: A dictionary of raw package metadata
		@type metadata: dict
		@rtype: List
		@return: A list of licenses that have not been accepted.
		"""
		accept_license = self._accept_license
		cpdict = self._plicensedict.get(dep_getkey(cpv), None)
		if cpdict:
			accept_license = list(self._accept_license)
			cpv_slot = "%s:%s" % (cpv, metadata["SLOT"])
			for atom in match_to_list(cpv_slot, list(cpdict)):
				accept_license.extend(cpdict[atom])

		licenses = set(flatten(dep.use_reduce(dep.paren_reduce(
			metadata["LICENSE"]), matchall=1)))
		licenses.discard('||')

		acceptable_licenses = set()
		for x in accept_license:
			if x == '*':
				acceptable_licenses.update(licenses)
			elif x == '-*':
				acceptable_licenses.clear()
			elif x[:1] == '-':
				acceptable_licenses.discard(x[1:])
			else:
				acceptable_licenses.add(x)

		license_str = metadata["LICENSE"]
		if "?" in license_str:
			use = metadata["USE"].split()
		else:
			use = []

		license_struct = portage.dep.use_reduce(
			portage.dep.paren_reduce(license_str), uselist=use)
		license_struct = portage.dep.dep_opconvert(license_struct)
		return self._getMaskedLicenses(license_struct, acceptable_licenses)

	def _getMaskedLicenses(self, license_struct, acceptable_licenses):
		if not license_struct:
			return []
		if license_struct[0] == "||":
			ret = []
			for element in license_struct[1:]:
				if isinstance(element, list):
					if element:
						ret.append(self._getMaskedLicenses(
							element, acceptable_licenses))
						if not ret[-1]:
							return []
				else:
					if element in acceptable_licenses:
						return []
					ret.append(element)
			# Return all masked licenses, since we don't know which combination
			# (if any) the user will decide to unmask.
			return flatten(ret)

		ret = []
		for element in license_struct:
			if isinstance(element, list):
				if element:
					ret.extend(self._getMaskedLicenses(element,
						acceptable_licenses))
			else:
				if element not in acceptable_licenses:
					ret.append(element)
		return ret

	def _getMissingProperties(self, cpv, metadata):
		"""
		Take a PROPERTIES string and return a list of any properties the user may
		may need to accept for the given package.  The returned list will not
		contain any properties that have already been accepted.  This method
		can throw an InvalidDependString exception.

		@param cpv: The package name (for package.properties support)
		@type cpv: String
		@param metadata: A dictionary of raw package metadata
		@type metadata: dict
		@rtype: List
		@return: A list of properties that have not been accepted.
		"""
		accept_properties = self._accept_properties
		cpdict = self._ppropertiesdict.get(dep_getkey(cpv), None)
		if cpdict:
			accept_properties = list(self._accept_properties)
			cpv_slot = "%s:%s" % (cpv, metadata["SLOT"])
			for atom in match_to_list(cpv_slot, list(cpdict)):
				accept_properties.extend(cpdict[atom])

		properties = set(flatten(dep.use_reduce(dep.paren_reduce(
			metadata["PROPERTIES"]), matchall=1)))
		properties.discard('||')

		acceptable_properties = set()
		for x in accept_properties:
			if x == '*':
				acceptable_properties.update(properties)
			elif x == '-*':
				acceptable_properties.clear()
			elif x[:1] == '-':
				acceptable_properties.discard(x[1:])
			else:
				acceptable_properties.add(x)

		properties_str = metadata["PROPERTIES"]
		if "?" in properties_str:
			use = metadata["USE"].split()
		else:
			use = []

		properties_struct = portage.dep.use_reduce(
			portage.dep.paren_reduce(properties_str), uselist=use)
		properties_struct = portage.dep.dep_opconvert(properties_struct)
		return self._getMaskedProperties(properties_struct, acceptable_properties)

	def _getMaskedProperties(self, properties_struct, acceptable_properties):
		if not properties_struct:
			return []
		if properties_struct[0] == "||":
			ret = []
			for element in properties_struct[1:]:
				if isinstance(element, list):
					if element:
						ret.append(self._getMaskedProperties(
							element, acceptable_properties))
						if not ret[-1]:
							return []
				else:
					if element in acceptable_properties:
						return[]
					ret.append(element)
			# Return all masked properties, since we don't know which combination
			# (if any) the user will decide to unmask
			return flatten(ret)

		ret = []
		for element in properties_struct:
			if isinstance(element, list):
				if element:
					ret.extend(self._getMaskedProperties(element,
						acceptable_properties))
			else:
				if element not in acceptable_properties:
					ret.append(element)
		return ret

	def _accept_chost(self, cpv, metadata):
		"""
		@return True if pkg CHOST is accepted, False otherwise.
		"""
		if self._accept_chost_re is None:
			accept_chost = self.get("ACCEPT_CHOSTS", "").split()
			if not accept_chost:
				chost = self.get("CHOST")
				if chost:
					accept_chost.append(chost)
			if not accept_chost:
				self._accept_chost_re = re.compile(".*")
			elif len(accept_chost) == 1:
				try:
					self._accept_chost_re = re.compile(r'^%s$' % accept_chost[0])
				except re.error as e:
					writemsg(_("!!! Invalid ACCEPT_CHOSTS value: '%s': %s\n") % \
						(accept_chost[0], e), noiselevel=-1)
					self._accept_chost_re = re.compile("^$")
			else:
				try:
					self._accept_chost_re = re.compile(
						r'^(%s)$' % "|".join(accept_chost))
				except re.error as e:
					writemsg(_("!!! Invalid ACCEPT_CHOSTS value: '%s': %s\n") % \
						(" ".join(accept_chost), e), noiselevel=-1)
					self._accept_chost_re = re.compile("^$")

		return self._accept_chost_re.match(
			metadata.get('CHOST', '')) is not None

	def setinst(self,mycpv,mydbapi):
		"""This updates the preferences for old-style virtuals,
		affecting the behavior of dep_expand() and dep_check()
		calls. It can change dbapi.match() behavior since that
		calls dep_expand(). However, dbapi instances have
		internal match caches that are not invalidated when
		preferences are updated here. This can potentially
		lead to some inconsistency (relevant to bug #1343)."""
		self.modifying()
		if len(self.virtuals) == 0:
			self.getvirtuals()
		# Grab the virtuals this package provides and add them into the tree virtuals.
		if not hasattr(mydbapi, "aux_get"):
			provides = mydbapi["PROVIDE"]
		else:
			provides = mydbapi.aux_get(mycpv, ["PROVIDE"])[0]
		if not provides:
			return
		if isinstance(mydbapi, portdbapi):
			self.setcpv(mycpv, mydb=mydbapi)
			myuse = self["PORTAGE_USE"]
		elif not hasattr(mydbapi, "aux_get"):
			myuse = mydbapi["USE"]
		else:
			myuse = mydbapi.aux_get(mycpv, ["USE"])[0]
		virts = flatten(portage.dep.use_reduce(portage.dep.paren_reduce(provides), uselist=myuse.split()))

		modified = False
		cp = dep.Atom(cpv_getkey(mycpv))
		for virt in virts:
			virt = dep_getkey(virt)
			providers = self.virtuals.get(virt)
			if providers and cp in providers:
				continue
			providers = self._depgraphVirtuals.get(virt)
			if providers is None:
				providers = []
				self._depgraphVirtuals[virt] = providers
			if cp not in providers:
				providers.append(cp)
				modified = True

		if modified:
			self.virtuals = self.__getvirtuals_compile()

	def reload(self):
		"""Reload things like /etc/profile.env that can change during runtime."""
		env_d_filename = os.path.join(self["ROOT"], "etc", "profile.env")
		self.configdict["env.d"].clear()
		env_d = getconfig(env_d_filename, expand=False)
		if env_d:
			# env_d will be None if profile.env doesn't exist.
			self.configdict["env.d"].update(env_d)

	def _prune_incremental(self, split):
		"""
		Prune off any parts of an incremental variable that are
		made irrelevant by the latest occuring * or -*. This
		could be more aggressive but that might be confusing
		and the point is just to reduce noise a bit.
		"""
		for i, x in enumerate(reversed(split)):
			if x == '*':
				split = split[-i-1:]
				break
			elif x == '-*':
				if i == 0:
					split = []
				else:
					split = split[-i:]
				break
		return split

	def regenerate(self,useonly=0,use_cache=1):
		"""
		Regenerate settings
		This involves regenerating valid USE flags, re-expanding USE_EXPAND flags
		re-stacking USE flags (-flag and -*), as well as any other INCREMENTAL
		variables.  This also updates the env.d configdict; useful in case an ebuild
		changes the environment.

		If FEATURES has already stacked, it is not stacked twice.

		@param useonly: Only regenerate USE flags (not any other incrementals)
		@type useonly: Boolean
		@param use_cache: Enable Caching (only for autouse)
		@type use_cache: Boolean
		@rtype: None
		"""

		self.modifying()
		if self.already_in_regenerate:
			# XXX: THIS REALLY NEEDS TO GET FIXED. autouse() loops.
			writemsg("!!! Looping in regenerate.\n",1)
			return
		else:
			self.already_in_regenerate = 1

		if useonly:
			myincrementals=["USE"]
		else:
			myincrementals = self.incrementals
		myincrementals = set(myincrementals)
		# If self.features exists, it has already been stacked and may have
		# been mutated, so don't stack it again or else any mutations will be
		# reverted.
		if "FEATURES" in myincrementals and hasattr(self, "features"):
			myincrementals.remove("FEATURES")

		if "USE" in myincrementals:
			# Process USE last because it depends on USE_EXPAND which is also
			# an incremental!
			myincrementals.remove("USE")

		mydbs = self.configlist[:-1]
		mydbs.append(self.backupenv)

		# ACCEPT_LICENSE is a lazily evaluated incremental, so that * can be
		# used to match all licenses without every having to explicitly expand
		# it to all licenses.
		if self.local_config:
			mysplit = []
			for curdb in mydbs:
				mysplit.extend(curdb.get('ACCEPT_LICENSE', '').split())
			mysplit = self._prune_incremental(mysplit)
			accept_license_str = ' '.join(mysplit)
			self.configlist[-1]['ACCEPT_LICENSE'] = accept_license_str
			if accept_license_str != self._accept_license_str:
				self._accept_license_str = accept_license_str
				self._accept_license = tuple(self.expandLicenseTokens(mysplit))
		else:
			# repoman will accept any license
			self._accept_license = ('*',)

		# ACCEPT_PROPERTIES works like ACCEPT_LICENSE, without groups
		if self.local_config:
			mysplit = []
			for curdb in mydbs:
				mysplit.extend(curdb.get('ACCEPT_PROPERTIES', '').split())
			mysplit = self._prune_incremental(mysplit)
			self.configlist[-1]['ACCEPT_PROPERTIES'] = ' '.join(mysplit)
			if tuple(mysplit) != self._accept_properties:
				self._accept_properties = tuple(mysplit)
		else:
			# repoman will accept any property
			self._accept_properties = ('*',)

		for mykey in myincrementals:

			myflags=[]
			for curdb in mydbs:
				if mykey not in curdb:
					continue
				#variables are already expanded
				mysplit = curdb[mykey].split()

				for x in mysplit:
					if x=="-*":
						# "-*" is a special "minus" var that means "unset all settings".
						# so USE="-* gnome" will have *just* gnome enabled.
						myflags = []
						continue

					if x[0]=="+":
						# Not legal. People assume too much. Complain.
						writemsg(colorize("BAD",
							_("USE flags should not start with a '+': %s") % x) \
							+ "\n", noiselevel=-1)
						x=x[1:]
						if not x:
							continue

					if (x[0]=="-"):
						if (x[1:] in myflags):
							# Unset/Remove it.
							del myflags[myflags.index(x[1:])]
						continue

					# We got here, so add it now.
					if x not in myflags:
						myflags.append(x)

			myflags.sort()
			#store setting in last element of configlist, the original environment:
			if myflags or mykey in self:
				self.configlist[-1][mykey] = " ".join(myflags)
			del myflags

		# Do the USE calculation last because it depends on USE_EXPAND.
		if "auto" in self["USE_ORDER"].split(":"):
			self.configdict["auto"]["USE"] = autouse(
				vartree(root=self["ROOT"], categories=self.categories,
					settings=self),
				use_cache=use_cache, mysettings=self)
		else:
			self.configdict["auto"]["USE"] = ""

		use_expand = self.get("USE_EXPAND", "").split()
		use_expand_dict = self._use_expand_dict
		use_expand_dict.clear()
		for k in use_expand:
			v = self.get(k)
			if v is not None:
				use_expand_dict[k] = v

		if not self.uvlist:
			for x in self["USE_ORDER"].split(":"):
				if x in self.configdict:
					self.uvlist.append(self.configdict[x])
			self.uvlist.reverse()

		# For optimal performance, use slice
		# comparison instead of startswith().
		myflags = set()
		for curdb in self.uvlist:
			cur_use_expand = [x for x in use_expand if x in curdb]
			mysplit = curdb.get("USE", "").split()
			if not mysplit and not cur_use_expand:
				continue
			for x in mysplit:
				if x == "-*":
					myflags.clear()
					continue

				if x[0] == "+":
					writemsg(colorize("BAD", _("USE flags should not start "
						"with a '+': %s\n") % x), noiselevel=-1)
					x = x[1:]
					if not x:
						continue

				if x[0] == "-":
					myflags.discard(x[1:])
					continue

				myflags.add(x)

			for var in cur_use_expand:
				var_lower = var.lower()
				is_not_incremental = var not in myincrementals
				if is_not_incremental:
					prefix = var_lower + "_"
					prefix_len = len(prefix)
					for x in list(myflags):
						if x[:prefix_len] == prefix:
							myflags.remove(x)
				for x in curdb[var].split():
					if x[0] == "+":
						if is_not_incremental:
							writemsg(colorize("BAD", _("Invalid '+' "
								"operator in non-incremental variable "
								 "'%s': '%s'\n") % (var, x)), noiselevel=-1)
							continue
						else:
							writemsg(colorize("BAD", _("Invalid '+' "
								"operator in incremental variable "
								 "'%s': '%s'\n") % (var, x)), noiselevel=-1)
						x = x[1:]
					if x[0] == "-":
						if is_not_incremental:
							writemsg(colorize("BAD", _("Invalid '-' "
								"operator in non-incremental variable "
								 "'%s': '%s'\n") % (var, x)), noiselevel=-1)
							continue
						myflags.discard(var_lower + "_" + x[1:])
						continue
					myflags.add(var_lower + "_" + x)

		if hasattr(self, "features"):
			self.features.clear()
		else:
			self.features = set()
		self.features.update(self.configlist[-1].get('FEATURES', '').split())
		self['FEATURES'] = ' '.join(sorted(self.features))

		myflags.update(self.useforce)
		arch = self.configdict["defaults"].get("ARCH")
		if arch:
			myflags.add(arch)

		myflags.difference_update(self.usemask)
		self.configlist[-1]["USE"]= " ".join(sorted(myflags))

		self.already_in_regenerate = 0

	def get_virts_p(self, myroot=None):
		if self.virts_p:
			return self.virts_p
		virts = self.getvirtuals()
		if virts:
			for x in virts:
				vkeysplit = x.split("/")
				if vkeysplit[1] not in self.virts_p:
					self.virts_p[vkeysplit[1]] = virts[x]
		return self.virts_p

	def getvirtuals(self, myroot=None):
		"""myroot is now ignored because, due to caching, it has always been
		broken for all but the first call."""
		myroot = self["ROOT"]
		if self.virtuals:
			return self.virtuals

		virtuals_list = []
		for x in self.profiles:
			virtuals_file = os.path.join(x, "virtuals")
			virtuals_dict = grabdict(virtuals_file)
			atoms_dict = {}
			for k, v in virtuals_dict.items():
				try:
					virt_atom = portage.dep.Atom(k)
				except portage.exception.InvalidAtom:
					virt_atom = None
				else:
					if virt_atom.blocker or \
						str(virt_atom) != str(virt_atom.cp):
						virt_atom = None
				if virt_atom is None:
					writemsg(_("--- Invalid virtuals atom in %s: %s\n") % \
						(virtuals_file, k), noiselevel=-1)
					continue
				providers = []
				for atom in v:
					atom_orig = atom
					if atom[:1] == '-':
						# allow incrementals
						atom = atom[1:]
					try:
						atom = portage.dep.Atom(atom)
					except portage.exception.InvalidAtom:
						atom = None
					else:
						if atom.blocker:
							atom = None
					if atom is None:
						writemsg(_("--- Invalid atom in %s: %s\n") % \
							(virtuals_file, myatom), noiselevel=-1)
					else:
						if atom_orig == str(atom):
							# normal atom, so return as Atom instance
							providers.append(atom)
						else:
							# atom has special prefix, so return as string
							providers.append(atom_orig)
				if providers:
					atoms_dict[virt_atom] = providers
			if atoms_dict:
				virtuals_list.append(atoms_dict)

		self.dirVirtuals = stack_dictlist(virtuals_list, incremental=True)
		del virtuals_list

		for virt in self.dirVirtuals:
			# Preference for virtuals decreases from left to right.
			self.dirVirtuals[virt].reverse()

		# Repoman does not use user or tree virtuals.
		if self.local_config and not self.treeVirtuals:
			temp_vartree = vartree(myroot, None,
				categories=self.categories, settings=self)
			self._populate_treeVirtuals(temp_vartree)

		self.virtuals = self.__getvirtuals_compile()
		return self.virtuals

	def _populate_treeVirtuals(self, vartree):
		"""Reduce the provides into a list by CP."""
		for provide, cpv_list in vartree.get_all_provides().items():
			try:
				provide = dep.Atom(provide)
			except exception.InvalidAtom:
				continue
			self.treeVirtuals[provide.cp] = \
				[dep.Atom(cpv_getkey(cpv)) for cpv in cpv_list]

	def __getvirtuals_compile(self):
		"""Stack installed and profile virtuals.  Preference for virtuals
		decreases from left to right.
		Order of preference:
		1. installed and in profile
		2. installed only
		3. profile only
		"""

		# Virtuals by profile+tree preferences.
		ptVirtuals   = {}

		for virt, installed_list in self.treeVirtuals.items():
			profile_list = self.dirVirtuals.get(virt, None)
			if not profile_list:
				continue
			for cp in installed_list:
				if cp in profile_list:
					ptVirtuals.setdefault(virt, [])
					ptVirtuals[virt].append(cp)

		virtuals = stack_dictlist([ptVirtuals, self.treeVirtuals,
			self.dirVirtuals, self._depgraphVirtuals])
		return virtuals

	def __delitem__(self,mykey):
		self.modifying()
		for x in self.lookuplist:
			if x != None:
				if mykey in x:
					del x[mykey]

	def __getitem__(self,mykey):
		for d in self.lookuplist:
			if mykey in d:
				return d[mykey]
		return '' # for backward compat, don't raise KeyError

	def get(self, k, x=None):
		for d in self.lookuplist:
			if k in d:
				return d[k]
		return x

	def pop(self, key, *args):
		if len(args) > 1:
			raise TypeError(
				"pop expected at most 2 arguments, got " + \
				repr(1 + len(args)))
		v = self
		for d in reversed(self.lookuplist):
			v = d.pop(key, v)
		if v is self:
			if args:
				return args[0]
			raise KeyError(key)
		return v

	def has_key(self,mykey):
		warnings.warn("portage.config.has_key() is deprecated, "
			"use the in operator instead",
			DeprecationWarning)
		return mykey in self

	def __contains__(self, mykey):
		"""Called to implement membership test operators (in and not in)."""
		for d in self.lookuplist:
			if mykey in d:
				return True
		return False

	def setdefault(self, k, x=None):
		v = self.get(k)
		if v is not None:
			return v
		else:
			self[k] = x
			return x

	def keys(self):
		return list(self)

	def __iter__(self):
		keys = set()
		for d in self.lookuplist:
			keys.update(d)
		return iter(keys)

	def iterkeys(self):
		return iter(self)

	def iteritems(self):
		for k in self:
			yield (k, self[k])

	def items(self):
		return list(self.iteritems())

	def __setitem__(self,mykey,myvalue):
		"set a value; will be thrown away at reset() time"
		if not isinstance(myvalue, basestring):
			raise ValueError("Invalid type being used as a value: '%s': '%s'" % (str(mykey),str(myvalue)))

		# Avoid potential UnicodeDecodeError exceptions later.
		mykey = _unicode_decode(mykey)
		myvalue = _unicode_decode(myvalue)

		self.modifying()
		self.modifiedkeys.append(mykey)
		self.configdict["env"][mykey]=myvalue

	def environ(self):
		"return our locally-maintained environment"
		mydict={}
		environ_filter = self._environ_filter

		phase = self.get('EBUILD_PHASE')
		filter_calling_env = False
		if phase not in ('clean', 'cleanrm', 'depend'):
			temp_dir = self.get('T')
			if temp_dir is not None and \
				os.path.exists(os.path.join(temp_dir, 'environment')):
				filter_calling_env = True

		environ_whitelist = self._environ_whitelist
		env_d = self.configdict["env.d"]
		for x in self:
			if x in environ_filter:
				continue
			myvalue = self[x]
			if not isinstance(myvalue, basestring):
				writemsg(_("!!! Non-string value in config: %s=%s\n") % \
					(x, myvalue), noiselevel=-1)
				continue
			if filter_calling_env and \
				x not in environ_whitelist and \
				not self._environ_whitelist_re.match(x):
				# Do not allow anything to leak into the ebuild
				# environment unless it is explicitly whitelisted.
				# This ensures that variables unset by the ebuild
				# remain unset.
				continue
			mydict[x] = myvalue
		if "HOME" not in mydict and "BUILD_PREFIX" in mydict:
			writemsg("*** HOME not set. Setting to "+mydict["BUILD_PREFIX"]+"\n")
			mydict["HOME"]=mydict["BUILD_PREFIX"][:]

		if filter_calling_env:
			if phase:
				whitelist = []
				if "rpm" == phase:
					whitelist.append("RPMDIR")
				for k in whitelist:
					v = self.get(k)
					if v is not None:
						mydict[k] = v

		# Filtered by IUSE and implicit IUSE.
		mydict["USE"] = self.get("PORTAGE_USE", "")

		# sandbox's bashrc sources /etc/profile which unsets ROOTPATH,
		# so we have to back it up and restore it.
		rootpath = mydict.get("ROOTPATH")
		if rootpath:
			mydict["PORTAGE_ROOTPATH"] = rootpath

		return mydict

	def thirdpartymirrors(self):
		if getattr(self, "_thirdpartymirrors", None) is None:
			profileroots = [os.path.join(self["PORTDIR"], "profiles")]
			for x in self["PORTDIR_OVERLAY"].split():
				profileroots.insert(0, os.path.join(x, "profiles"))
			thirdparty_lists = [grabdict(os.path.join(x, "thirdpartymirrors")) for x in profileroots]
			self._thirdpartymirrors = stack_dictlist(thirdparty_lists, incremental=True)
		return self._thirdpartymirrors

	def archlist(self):
		return flatten([[myarch, "~" + myarch] \
			for myarch in self["PORTAGE_ARCHLIST"].split()])

	def selinux_enabled(self):
		if getattr(self, "_selinux_enabled", None) is None:
			self._selinux_enabled = 0
			if "selinux" in self["USE"].split():
				if selinux:
					if selinux.is_selinux_enabled() == 1:
						self._selinux_enabled = 1
					else:
						self._selinux_enabled = 0
				else:
					writemsg(_("!!! SELinux module not found. Please verify that it was installed.\n"),
						noiselevel=-1)
					self._selinux_enabled = 0

		return self._selinux_enabled

	if sys.hexversion >= 0x3000000:
		keys = __iter__
		items = iteritems

def _can_test_pty_eof():
	"""
	The _test_pty_eof() function seems to hang on most
	kernels other than Linux.
	@rtype: bool
	@returns: True if _test_pty_eof() won't hang, False otherwise.
	"""
	return platform.system() in ("Linux",)

def _test_pty_eof():
	"""
	Returns True if this issues is fixed for the currently
	running version of python: http://bugs.python.org/issue5380
	Raises an EnvironmentError from openpty() if it fails.
	"""

	use_fork = False

	import array, fcntl, pty, select, termios
	test_string = 2 * "blah blah blah\n"
	test_string = _unicode_decode(test_string,
		encoding='utf_8', errors='strict')

	# may raise EnvironmentError
	master_fd, slave_fd = pty.openpty()

	# Non-blocking mode is required for Darwin kernel.
	fcntl.fcntl(master_fd, fcntl.F_SETFL,
		fcntl.fcntl(master_fd, fcntl.F_GETFL) | os.O_NONBLOCK)

	# Disable post-processing of output since otherwise weird
	# things like \n -> \r\n transformations may occur.
	mode = termios.tcgetattr(slave_fd)
	mode[1] &= ~termios.OPOST
	termios.tcsetattr(slave_fd, termios.TCSANOW, mode)

	# Simulate a subprocess writing some data to the
	# slave end of the pipe, and then exiting.
	pid = None
	if use_fork:
		pids = process.spawn_bash(_unicode_encode("echo -n '%s'" % test_string,
			encoding='utf_8', errors='strict'), env=os.environ,
			fd_pipes={0:sys.stdin.fileno(), 1:slave_fd, 2:slave_fd},
			returnpid=True)
		if isinstance(pids, int):
			os.close(master_fd)
			os.close(slave_fd)
			raise EnvironmentError('spawn failed')
		pid = pids[0]
	else:
		os.write(slave_fd, _unicode_encode(test_string,
			encoding='utf_8', errors='strict'))
	os.close(slave_fd)

	# If using a fork, we must wait for the child here,
	# in order to avoid a race condition that would
	# lead to inconsistent results.
	if pid is not None:
		os.waitpid(pid, 0)

	master_file = os.fdopen(master_fd, 'rb')
	eof = False
	data = []
	iwtd = [master_file]
	owtd = []
	ewtd = []

	while not eof:

		events = select.select(iwtd, owtd, ewtd)
		if not events[0]:
			eof = True
			break

		buf = array.array('B')
		try:
			buf.fromfile(master_file, 1024)
		except EOFError:
			eof = True
		except IOError:
			# This is where data loss occurs.
			eof = True

		if not buf:
			eof = True
		else:
			data.append(_unicode_decode(buf.tostring(),
				encoding='utf_8', errors='strict'))

	master_file.close()

	return test_string == ''.join(data)

# If _test_pty_eof() can't be used for runtime detection of
# http://bugs.python.org/issue5380, openpty can't safely be used
# unless we can guarantee that the current version of python has
# been fixed (affects all current versions of python3). When
# this issue is fixed in python3, we can add another sys.hexversion
# conditional to enable openpty support in the fixed versions.
if sys.hexversion >= 0x3000000 and not _can_test_pty_eof():
	# Disable the use of openpty on Solaris as it seems Python's openpty
	# implementation doesn't play nice on Solaris with Portage's
	# behaviour causing hangs/deadlocks.
	# Disable on Darwin also, it used to work fine, but since the
	# introduction of _test_pty_eof Portage hangs (on the
	# slave_file.close()) indicating some other problems with openpty on
	# Darwin there
	# On AIX, haubi reported that the openpty code doesn't work any
	# longer since the introduction of _test_pty_eof either.
	# Looks like Python's openpty module is too fragile to use on UNIX,
	# so only use it on Linux
	_disable_openpty = True
else:
	_disable_openpty = False
_tested_pty = False

if not _can_test_pty_eof():
	# Skip _test_pty_eof() on systems where it hangs.
	_tested_pty = True

def _create_pty_or_pipe(copy_term_size=None):
	"""
	Try to create a pty and if then fails then create a normal
	pipe instead.

	@param copy_term_size: If a tty file descriptor is given
		then the term size will be copied to the pty.
	@type copy_term_size: int
	@rtype: tuple
	@returns: A tuple of (is_pty, master_fd, slave_fd) where
		is_pty is True if a pty was successfully allocated, and
		False if a normal pipe was allocated.
	"""

	got_pty = False

	global _disable_openpty, _tested_pty
	if not (_tested_pty or _disable_openpty):
		try:
			if not _test_pty_eof():
				_disable_openpty = True
		except EnvironmentError as e:
			_disable_openpty = True
			writemsg("openpty failed: '%s'\n" % str(e),
				noiselevel=-1)
			del e
		_tested_pty = True

	if _disable_openpty:
		master_fd, slave_fd = os.pipe()
	else:
		from pty import openpty
		try:
			master_fd, slave_fd = openpty()
			got_pty = True
		except EnvironmentError as e:
			_disable_openpty = True
			writemsg("openpty failed: '%s'\n" % str(e),
				noiselevel=-1)
			del e
			master_fd, slave_fd = os.pipe()

	if got_pty:
		# Disable post-processing of output since otherwise weird
		# things like \n -> \r\n transformations may occur.
		import termios
		mode = termios.tcgetattr(slave_fd)
		mode[1] &= ~termios.OPOST
		termios.tcsetattr(slave_fd, termios.TCSANOW, mode)

	if got_pty and \
		copy_term_size is not None and \
		os.isatty(copy_term_size):
		from portage.output import get_term_size, set_term_size
		rows, columns = get_term_size()
		set_term_size(rows, columns, slave_fd)

	return (got_pty, master_fd, slave_fd)

# XXX This would be to replace getstatusoutput completely.
# XXX Issue: cannot block execution. Deadlock condition.
def spawn(mystring, mysettings, debug=0, free=0, droppriv=0, sesandbox=0, fakeroot=0, **keywords):
	"""
	Spawn a subprocess with extra portage-specific options.
	Optiosn include:

	Sandbox: Sandbox means the spawned process will be limited in its ability t
	read and write files (normally this means it is restricted to ${IMAGE}/)
	SElinux Sandbox: Enables sandboxing on SElinux
	Reduced Privileges: Drops privilages such that the process runs as portage:portage
	instead of as root.

	Notes: os.system cannot be used because it messes with signal handling.  Instead we
	use the portage.process spawn* family of functions.

	This function waits for the process to terminate.

	@param mystring: Command to run
	@type mystring: String
	@param mysettings: Either a Dict of Key,Value pairs or an instance of portage.config
	@type mysettings: Dictionary or config instance
	@param debug: Ignored
	@type debug: Boolean
	@param free: Enable sandboxing for this process
	@type free: Boolean
	@param droppriv: Drop to portage:portage when running this command
	@type droppriv: Boolean
	@param sesandbox: Enable SELinux Sandboxing (toggles a context switch)
	@type sesandbox: Boolean
	@param fakeroot: Run this command with faked root privileges
	@type fakeroot: Boolean
	@param keywords: Extra options encoded as a dict, to be passed to spawn
	@type keywords: Dictionary
	@rtype: Integer
	@returns:
	1. The return code of the spawned process.
	"""

	if isinstance(mysettings, dict):
		env=mysettings
		keywords["opt_name"]="[ %s ]" % "portage"
	else:
		check_config_instance(mysettings)
		env=mysettings.environ()
		if mysettings.mycpv is not None:
			keywords["opt_name"] = "[%s]" % mysettings.mycpv
		else:
			keywords["opt_name"] = "[%s/%s]" % \
				(mysettings.get("CATEGORY",""), mysettings.get("PF",""))

	fd_pipes = keywords.get("fd_pipes")
	if fd_pipes is None:
		fd_pipes = {
			0:sys.stdin.fileno(),
			1:sys.stdout.fileno(),
			2:sys.stderr.fileno(),
		}
	# In some cases the above print statements don't flush stdout, so
	# it needs to be flushed before allowing a child process to use it
	# so that output always shows in the correct order.
	stdout_filenos = (sys.stdout.fileno(), sys.stderr.fileno())
	for fd in fd_pipes.values():
		if fd in stdout_filenos:
			sys.stdout.flush()
			sys.stderr.flush()
			break

	# The default policy for the sesandbox domain only allows entry (via exec)
	# from shells and from binaries that belong to portage (the number of entry
	# points is minimized).  The "tee" binary is not among the allowed entry
	# points, so it is spawned outside of the sesandbox domain and reads from a
	# pseudo-terminal that connects two domains.
	logfile = keywords.get("logfile")
	mypids = []
	master_fd = None
	slave_fd = None
	fd_pipes_orig = None
	got_pty = False
	if logfile:
		del keywords["logfile"]
		if 1 not in fd_pipes or 2 not in fd_pipes:
			raise ValueError(fd_pipes)

		fd_pipes.setdefault(0, sys.stdin.fileno())
		fd_pipes_orig = fd_pipes.copy()

		got_pty, master_fd, slave_fd = \
			_create_pty_or_pipe(copy_term_size=fd_pipes_orig[1])

		# We must set non-blocking mode before we close the slave_fd
		# since otherwise the fcntl call can fail on FreeBSD (the child
		# process might have already exited and closed slave_fd so we
		# have to keep it open in order to avoid FreeBSD potentially
		# generating an EAGAIN exception).
		import fcntl
		fcntl.fcntl(master_fd, fcntl.F_SETFL,
			fcntl.fcntl(master_fd, fcntl.F_GETFL) | os.O_NONBLOCK)

		fd_pipes[0] = fd_pipes_orig[0]
		fd_pipes[1] = slave_fd
		fd_pipes[2] = slave_fd
		keywords["fd_pipes"] = fd_pipes

	features = mysettings.features
	# TODO: Enable fakeroot to be used together with droppriv.  The
	# fake ownership/permissions will have to be converted to real
	# permissions in the merge phase.
	fakeroot = fakeroot and uid != 0 and portage.process.fakeroot_capable
	if droppriv and not uid and portage_gid and portage_uid:
		keywords.update({"uid":portage_uid,"gid":portage_gid,
			"groups":userpriv_groups,"umask":0o02})
	if not free:
		free=((droppriv and "usersandbox" not in features) or \
			(not droppriv and "sandbox" not in features and \
			"usersandbox" not in features and not fakeroot))

	if free or "SANDBOX_ACTIVE" in os.environ:
		keywords["opt_name"] += " bash"
		spawn_func = portage.process.spawn_bash
	elif fakeroot:
		keywords["opt_name"] += " fakeroot"
		keywords["fakeroot_state"] = os.path.join(mysettings["T"], "fakeroot.state")
		spawn_func = portage.process.spawn_fakeroot
	else:
		keywords["opt_name"] += " sandbox"
		spawn_func = portage.process.spawn_sandbox

	if sesandbox:
		spawn_func = selinux.spawn_wrapper(spawn_func,
			mysettings["PORTAGE_SANDBOX_T"])

	returnpid = keywords.get("returnpid")
	keywords["returnpid"] = True
	try:
		mypids.extend(spawn_func(mystring, env=env, **keywords))
	finally:
		if logfile:
			os.close(slave_fd)

	if returnpid:
		return mypids

	if logfile:
		log_file = open(_unicode_encode(logfile), mode='ab')
		stdout_file = os.fdopen(os.dup(fd_pipes_orig[1]), 'wb')
		master_file = os.fdopen(master_fd, 'rb')
		iwtd = [master_file]
		owtd = []
		ewtd = []
		import array, select
		buffsize = 65536
		eof = False
		while not eof:
			events = select.select(iwtd, owtd, ewtd)
			for f in events[0]:
				# Use non-blocking mode to prevent read
				# calls from blocking indefinitely.
				buf = array.array('B')
				try:
					buf.fromfile(f, buffsize)
				except EOFError:
					pass
				if not buf:
					eof = True
					break
				if f is master_file:
					buf.tofile(stdout_file)
					stdout_file.flush()
					buf.tofile(log_file)
					log_file.flush()
		log_file.close()
		stdout_file.close()
		master_file.close()
	pid = mypids[-1]
	retval = os.waitpid(pid, 0)[1]
	portage.process.spawned_pids.remove(pid)
	if retval != os.EX_OK:
		if retval & 0xff:
			return (retval & 0xff) << 8
		return retval >> 8
	return retval

_userpriv_spawn_kwargs = (
	("uid",    portage_uid),
	("gid",    portage_gid),
	("groups", userpriv_groups),
	("umask",  0o02),
)

def _spawn_fetch(settings, args, **kwargs):
	"""
	Spawn a process with appropriate settings for fetching, including
	userfetch and selinux support.
	"""

	global _userpriv_spawn_kwargs

	# Redirect all output to stdout since some fetchers like
	# wget pollute stderr (if portage detects a problem then it
	# can send it's own message to stderr).
	if "fd_pipes" not in kwargs:

		kwargs["fd_pipes"] = {
			0 : sys.stdin.fileno(),
			1 : sys.stdout.fileno(),
			2 : sys.stdout.fileno(),
		}

	if "userfetch" in settings.features and \
		os.getuid() == 0 and portage_gid and portage_uid:
		kwargs.update(_userpriv_spawn_kwargs)

	spawn_func = portage.process.spawn

	if settings.selinux_enabled():
		spawn_func = selinux.spawn_wrapper(spawn_func,
			settings["PORTAGE_FETCH_T"])

		# bash is an allowed entrypoint, while most binaries are not
		if args[0] != BASH_BINARY:
			args = [BASH_BINARY, "-c", "exec \"$@\"", args[0]] + args

	rval = spawn_func(args, env=dict(iter(settings.items())), **kwargs)

	return rval

_userpriv_test_write_file_cache = {}
_userpriv_test_write_cmd_script = "touch %(file_path)s 2>/dev/null ; rval=$? ; " + \
	"rm -f  %(file_path)s ; exit $rval"

def _userpriv_test_write_file(settings, file_path):
	"""
	Drop privileges and try to open a file for writing. The file may or
	may not exist, and the parent directory is assumed to exist. The file
	is removed before returning.

	@param settings: A config instance which is passed to _spawn_fetch()
	@param file_path: A file path to open and write.
	@return: True if write succeeds, False otherwise.
	"""

	global _userpriv_test_write_file_cache, _userpriv_test_write_cmd_script
	rval = _userpriv_test_write_file_cache.get(file_path)
	if rval is not None:
		return rval

	args = [BASH_BINARY, "-c", _userpriv_test_write_cmd_script % \
		{"file_path" : _shell_quote(file_path)}]

	returncode = _spawn_fetch(settings, args)

	rval = returncode == os.EX_OK
	_userpriv_test_write_file_cache[file_path] = rval
	return rval

def _checksum_failure_temp_file(distdir, basename):
	"""
	First try to find a duplicate temp file with the same checksum and return
	that filename if available. Otherwise, use mkstemp to create a new unique
	filename._checksum_failure_.$RANDOM, rename the given file, and return the
	new filename. In any case, filename will be renamed or removed before this
	function returns a temp filename.
	"""

	filename = os.path.join(distdir, basename)
	size = os.stat(filename).st_size
	checksum = None
	tempfile_re = re.compile(re.escape(basename) + r'\._checksum_failure_\..*')
	for temp_filename in os.listdir(distdir):
		if not tempfile_re.match(temp_filename):
			continue
		temp_filename = os.path.join(distdir, temp_filename)
		try:
			if size != os.stat(temp_filename).st_size:
				continue
		except OSError:
			continue
		try:
			temp_checksum = portage.checksum.perform_md5(temp_filename)
		except portage.exception.FileNotFound:
			# Apparently the temp file disappeared. Let it go.
			continue
		if checksum is None:
			checksum = portage.checksum.perform_md5(filename)
		if checksum == temp_checksum:
			os.unlink(filename)
			return temp_filename

	from tempfile import mkstemp
	fd, temp_filename = mkstemp("", basename + "._checksum_failure_.", distdir)
	os.close(fd)
	os.rename(filename, temp_filename)
	return temp_filename

def _check_digests(filename, digests, show_errors=1):
	"""
	Check digests and display a message if an error occurs.
	@return True if all digests match, False otherwise.
	"""
	verified_ok, reason = portage.checksum.verify_all(filename, digests)
	if not verified_ok:
		if show_errors:
			writemsg(_("!!! Previously fetched"
				" file: '%s'\n") % filename, noiselevel=-1)
			writemsg(_("!!! Reason: %s\n") % reason[0],
				noiselevel=-1)
			writemsg(_("!!! Got:      %s\n"
				"!!! Expected: %s\n") % \
				(reason[1], reason[2]), noiselevel=-1)
		return False
	return True

def _check_distfile(filename, digests, eout, show_errors=1):
	"""
	@return a tuple of (match, stat_obj) where match is True if filename
	matches all given digests (if any) and stat_obj is a stat result, or
	None if the file does not exist.
	"""
	if digests is None:
		digests = {}
	size = digests.get("size")
	if size is not None and len(digests) == 1:
		digests = None

	try:
		st = os.stat(filename)
	except OSError:
		return (False, None)
	if size is not None and size != st.st_size:
		return (False, st)
	if not digests:
		if size is not None:
			eout.ebegin(_("%s size ;-)") % os.path.basename(filename))
			eout.eend(0)
		elif st.st_size == 0:
			# Zero-byte distfiles are always invalid.
			return (False, st)
	else:
		if _check_digests(filename, digests, show_errors=show_errors):
			eout.ebegin("%s %s ;-)" % (os.path.basename(filename),
				" ".join(sorted(digests))))
			eout.eend(0)
		else:
			return (False, st)
	return (True, st)

_fetch_resume_size_re = re.compile('(^[\d]+)([KMGTPEZY]?$)')

_size_suffix_map = {
	''  : 0,
	'K' : 10,
	'M' : 20,
	'G' : 30,
	'T' : 40,
	'P' : 50,
	'E' : 60,
	'Z' : 70,
	'Y' : 80,
}

def fetch(myuris, mysettings, listonly=0, fetchonly=0, locks_in_subdir=".locks",use_locks=1, try_mirrors=1):
	"fetch files.  Will use digest file if available."

	if not myuris:
		return 1

	features = mysettings.features
	restrict = mysettings.get("PORTAGE_RESTRICT","").split()

	from portage.data import secpass
	userfetch = secpass >= 2 and "userfetch" in features
	userpriv = secpass >= 2 and "userpriv" in features

	# 'nomirror' is bad/negative logic. You Restrict mirroring, not no-mirroring.
	if "mirror" in restrict or \
	   "nomirror" in restrict:
		if ("mirror" in features) and ("lmirror" not in features):
			# lmirror should allow you to bypass mirror restrictions.
			# XXX: This is not a good thing, and is temporary at best.
			print(_(">>> \"mirror\" mode desired and \"mirror\" restriction found; skipping fetch."))
			return 1

	# Generally, downloading the same file repeatedly from
	# every single available mirror is a waste of bandwidth
	# and time, so there needs to be a cap.
	checksum_failure_max_tries = 5
	v = checksum_failure_max_tries
	try:
		v = int(mysettings.get("PORTAGE_FETCH_CHECKSUM_TRY_MIRRORS",
			checksum_failure_max_tries))
	except (ValueError, OverflowError):
		writemsg(_("!!! Variable PORTAGE_FETCH_CHECKSUM_TRY_MIRRORS"
			" contains non-integer value: '%s'\n") % \
			mysettings["PORTAGE_FETCH_CHECKSUM_TRY_MIRRORS"], noiselevel=-1)
		writemsg(_("!!! Using PORTAGE_FETCH_CHECKSUM_TRY_MIRRORS "
			"default value: %s\n") % checksum_failure_max_tries,
			noiselevel=-1)
		v = checksum_failure_max_tries
	if v < 1:
		writemsg(_("!!! Variable PORTAGE_FETCH_CHECKSUM_TRY_MIRRORS"
			" contains value less than 1: '%s'\n") % v, noiselevel=-1)
		writemsg(_("!!! Using PORTAGE_FETCH_CHECKSUM_TRY_MIRRORS "
			"default value: %s\n") % checksum_failure_max_tries,
			noiselevel=-1)
		v = checksum_failure_max_tries
	checksum_failure_max_tries = v
	del v

	fetch_resume_size_default = "350K"
	fetch_resume_size = mysettings.get("PORTAGE_FETCH_RESUME_MIN_SIZE")
	if fetch_resume_size is not None:
		fetch_resume_size = "".join(fetch_resume_size.split())
		if not fetch_resume_size:
			# If it's undefined or empty, silently use the default.
			fetch_resume_size = fetch_resume_size_default
		match = _fetch_resume_size_re.match(fetch_resume_size)
		if match is None or \
			(match.group(2).upper() not in _size_suffix_map):
			writemsg(_("!!! Variable PORTAGE_FETCH_RESUME_MIN_SIZE"
				" contains an unrecognized format: '%s'\n") % \
				mysettings["PORTAGE_FETCH_RESUME_MIN_SIZE"], noiselevel=-1)
			writemsg(_("!!! Using PORTAGE_FETCH_RESUME_MIN_SIZE "
				"default value: %s\n") % fetch_resume_size_default,
				noiselevel=-1)
			fetch_resume_size = None
	if fetch_resume_size is None:
		fetch_resume_size = fetch_resume_size_default
		match = _fetch_resume_size_re.match(fetch_resume_size)
	fetch_resume_size = int(match.group(1)) * \
		2 ** _size_suffix_map[match.group(2).upper()]

	# Behave like the package has RESTRICT="primaryuri" after a
	# couple of checksum failures, to increase the probablility
	# of success before checksum_failure_max_tries is reached.
	checksum_failure_primaryuri = 2
	thirdpartymirrors = mysettings.thirdpartymirrors()

	# In the background parallel-fetch process, it's safe to skip checksum
	# verification of pre-existing files in $DISTDIR that have the correct
	# file size. The parent process will verify their checksums prior to
	# the unpack phase.

	parallel_fetchonly = "PORTAGE_PARALLEL_FETCHONLY" in mysettings
	if parallel_fetchonly:
		fetchonly = 1

	check_config_instance(mysettings)

	custommirrors = grabdict(os.path.join(mysettings["PORTAGE_CONFIGROOT"],
		CUSTOM_MIRRORS_FILE), recursive=1)

	mymirrors=[]

	if listonly or ("distlocks" not in features):
		use_locks = 0

	fetch_to_ro = 0
	if "skiprocheck" in features:
		fetch_to_ro = 1

	if not os.access(mysettings["DISTDIR"],os.W_OK) and fetch_to_ro:
		if use_locks:
			writemsg(colorize("BAD",
				_("!!! For fetching to a read-only filesystem, "
				"locking should be turned off.\n")), noiselevel=-1)
			writemsg(_("!!! This can be done by adding -distlocks to "
				"FEATURES in /etc/make.conf\n"), noiselevel=-1)
#			use_locks = 0

	# local mirrors are always added
	if "local" in custommirrors:
		mymirrors += custommirrors["local"]

	if "nomirror" in restrict or \
	   "mirror" in restrict:
		# We don't add any mirrors.
		pass
	else:
		if try_mirrors:
			mymirrors += [x.rstrip("/") for x in mysettings["GENTOO_MIRRORS"].split() if x]

	skip_manifest = mysettings.get("EBUILD_SKIP_MANIFEST") == "1"
	pkgdir = mysettings.get("O")
	if not (pkgdir is None or skip_manifest):
		mydigests = Manifest(
			pkgdir, mysettings["DISTDIR"]).getTypeDigests("DIST")
	else:
		# no digests because fetch was not called for a specific package
		mydigests = {}

	ro_distdirs = [x for x in \
		util.shlex_split(mysettings.get("PORTAGE_RO_DISTDIRS", "")) \
		if os.path.isdir(x)]

	fsmirrors = []
	for x in range(len(mymirrors)-1,-1,-1):
		if mymirrors[x] and mymirrors[x][0]=='/':
			fsmirrors += [mymirrors[x]]
			del mymirrors[x]

	restrict_fetch = "fetch" in restrict
	custom_local_mirrors = custommirrors.get("local", [])
	if restrict_fetch:
		# With fetch restriction, a normal uri may only be fetched from
		# custom local mirrors (if available).  A mirror:// uri may also
		# be fetched from specific mirrors (effectively overriding fetch
		# restriction, but only for specific mirrors).
		locations = custom_local_mirrors
	else:
		locations = mymirrors

	file_uri_tuples = []
	if isinstance(myuris, dict):
		for myfile, uri_set in myuris.items():
			for myuri in uri_set:
				file_uri_tuples.append((myfile, myuri))
	else:
		for myuri in myuris:
			file_uri_tuples.append((os.path.basename(myuri), myuri))

	filedict={}
	primaryuri_indexes={}
	primaryuri_dict = {}
	thirdpartymirror_uris = {}
	for myfile, myuri in file_uri_tuples:
		if myfile not in filedict:
			filedict[myfile]=[]
			for y in range(0,len(locations)):
				filedict[myfile].append(locations[y]+"/distfiles/"+myfile)
		if myuri[:9]=="mirror://":
			eidx = myuri.find("/", 9)
			if eidx != -1:
				mirrorname = myuri[9:eidx]
				path = myuri[eidx+1:]

				# Try user-defined mirrors first
				if mirrorname in custommirrors:
					for cmirr in custommirrors[mirrorname]:
						filedict[myfile].append(
							cmirr.rstrip("/") + "/" + path)

				# now try the official mirrors
				if mirrorname in thirdpartymirrors:
					shuffle(thirdpartymirrors[mirrorname])

					uris = [locmirr.rstrip("/") + "/" + path \
						for locmirr in thirdpartymirrors[mirrorname]]
					filedict[myfile].extend(uris)
					thirdpartymirror_uris.setdefault(myfile, []).extend(uris)

				if not filedict[myfile]:
					writemsg(_("No known mirror by the name: %s\n") % (mirrorname))
			else:
				writemsg(_("Invalid mirror definition in SRC_URI:\n"), noiselevel=-1)
				writemsg("  %s\n" % (myuri), noiselevel=-1)
		else:
			if restrict_fetch:
				# Only fetch from specific mirrors is allowed.
				continue
			if "primaryuri" in restrict:
				# Use the source site first.
				if myfile in primaryuri_indexes:
					primaryuri_indexes[myfile] += 1
				else:
					primaryuri_indexes[myfile] = 0
				filedict[myfile].insert(primaryuri_indexes[myfile], myuri)
			else:
				filedict[myfile].append(myuri)
			primaryuris = primaryuri_dict.get(myfile)
			if primaryuris is None:
				primaryuris = []
				primaryuri_dict[myfile] = primaryuris
			primaryuris.append(myuri)

	# Prefer thirdpartymirrors over normal mirrors in cases when
	# the file does not yet exist on the normal mirrors.
	for myfile, uris in thirdpartymirror_uris.items():
		primaryuri_dict.setdefault(myfile, []).extend(uris)

	can_fetch=True

	if listonly:
		can_fetch = False

	if can_fetch and not fetch_to_ro:
		global _userpriv_test_write_file_cache
		dirmode  = 0o2070
		filemode =   0o60
		modemask =    0o2
		dir_gid = portage_gid
		if "FAKED_MODE" in mysettings:
			# When inside fakeroot, directories with portage's gid appear
			# to have root's gid. Therefore, use root's gid instead of
			# portage's gid to avoid spurrious permissions adjustments
			# when inside fakeroot.
			dir_gid = 0
		distdir_dirs = [""]
		if "distlocks" in features:
			distdir_dirs.append(".locks")
		try:
			
			for x in distdir_dirs:
				mydir = os.path.join(mysettings["DISTDIR"], x)
				write_test_file = os.path.join(
					mydir, ".__portage_test_write__")

				try:
					st = os.stat(mydir)
				except OSError:
					st = None

				if st is not None and stat.S_ISDIR(st.st_mode):
					if not (userfetch or userpriv):
						continue
					if _userpriv_test_write_file(mysettings, write_test_file):
						continue

				_userpriv_test_write_file_cache.pop(write_test_file, None)
				if portage.util.ensure_dirs(mydir, gid=dir_gid, mode=dirmode, mask=modemask):
					if st is None:
						# The directory has just been created
						# and therefore it must be empty.
						continue
					writemsg(_("Adjusting permissions recursively: '%s'\n") % mydir,
						noiselevel=-1)
					def onerror(e):
						raise # bail out on the first error that occurs during recursion
					if not apply_recursive_permissions(mydir,
						gid=dir_gid, dirmode=dirmode, dirmask=modemask,
						filemode=filemode, filemask=modemask, onerror=onerror):
						raise portage.exception.OperationNotPermitted(
							_("Failed to apply recursive permissions for the portage group."))
		except portage.exception.PortageException as e:
			if not os.path.isdir(mysettings["DISTDIR"]):
				writemsg("!!! %s\n" % str(e), noiselevel=-1)
				writemsg(_("!!! Directory Not Found: DISTDIR='%s'\n") % mysettings["DISTDIR"], noiselevel=-1)
				writemsg(_("!!! Fetching will fail!\n"), noiselevel=-1)

	if can_fetch and \
		not fetch_to_ro and \
		not os.access(mysettings["DISTDIR"], os.W_OK):
		writemsg(_("!!! No write access to '%s'\n") % mysettings["DISTDIR"],
			noiselevel=-1)
		can_fetch = False

	if can_fetch and use_locks and locks_in_subdir:
			distlocks_subdir = os.path.join(mysettings["DISTDIR"], locks_in_subdir)
			if not os.access(distlocks_subdir, os.W_OK):
				writemsg(_("!!! No write access to write to %s.  Aborting.\n") % distlocks_subdir,
					noiselevel=-1)
				return 0
			del distlocks_subdir

	distdir_writable = can_fetch and not fetch_to_ro
	failed_files = set()
	restrict_fetch_msg = False

	for myfile in filedict:
		"""
		fetched  status
		0        nonexistent
		1        partially downloaded
		2        completely downloaded
		"""
		fetched = 0

		orig_digests = mydigests.get(myfile, {})
		size = orig_digests.get("size")
		if size == 0:
			# Zero-byte distfiles are always invalid, so discard their digests.
			del mydigests[myfile]
			orig_digests.clear()
			size = None
		pruned_digests = orig_digests
		if parallel_fetchonly:
			pruned_digests = {}
			if size is not None:
				pruned_digests["size"] = size

		myfile_path = os.path.join(mysettings["DISTDIR"], myfile)
		has_space = True
		has_space_superuser = True
		file_lock = None
		if listonly:
			writemsg_stdout("\n", noiselevel=-1)
		else:
			# check if there is enough space in DISTDIR to completely store myfile
			# overestimate the filesize so we aren't bitten by FS overhead
			if size is not None and hasattr(os, "statvfs"):
				vfs_stat = os.statvfs(mysettings["DISTDIR"])
				try:
					mysize = os.stat(myfile_path).st_size
				except OSError as e:
					if e.errno not in (errno.ENOENT, errno.ESTALE):
						raise
					del e
					mysize = 0
				if (size - mysize + vfs_stat.f_bsize) >= \
					(vfs_stat.f_bsize * vfs_stat.f_bavail):

					if (size - mysize + vfs_stat.f_bsize) >= \
						(vfs_stat.f_bsize * vfs_stat.f_bfree):
						has_space_superuser = False

					if not has_space_superuser:
						has_space = False
					elif secpass < 2:
						has_space = False
					elif userfetch:
						has_space = False

			if not has_space:
				writemsg(_("!!! Insufficient space to store %s in %s\n") % \
					(myfile, mysettings["DISTDIR"]), noiselevel=-1)

				if has_space_superuser:
					writemsg(_("!!! Insufficient privileges to use "
						"remaining space.\n"), noiselevel=-1)
					if userfetch:
						writemsg(_("!!! You may set FEATURES=\"-userfetch\""
							" in /etc/make.conf in order to fetch with\n"
							"!!! superuser privileges.\n"), noiselevel=-1)

			if distdir_writable and use_locks:

				if locks_in_subdir:
					lock_file = os.path.join(mysettings["DISTDIR"],
						locks_in_subdir, myfile)
				else:
					lock_file = myfile_path

				lock_kwargs = {}
				if fetchonly:
					lock_kwargs["flags"] = os.O_NONBLOCK

				try:
					file_lock = portage.locks.lockfile(myfile_path,
						wantnewlockfile=1, **lock_kwargs)
				except portage.exception.TryAgain:
					writemsg(_(">>> File '%s' is already locked by "
						"another fetcher. Continuing...\n") % myfile,
						noiselevel=-1)
					continue
		try:
			if not listonly:

				eout = portage.output.EOutput()
				eout.quiet = mysettings.get("PORTAGE_QUIET") == "1"
				match, mystat = _check_distfile(
					myfile_path, pruned_digests, eout)
				if match:
					if distdir_writable:
						try:
							apply_secpass_permissions(myfile_path,
								gid=portage_gid, mode=0o664, mask=0o2,
								stat_cached=mystat)
						except portage.exception.PortageException as e:
							if not os.access(myfile_path, os.R_OK):
								writemsg(_("!!! Failed to adjust permissions:"
									" %s\n") % str(e), noiselevel=-1)
							del e
					continue

				if distdir_writable and mystat is None:
					# Remove broken symlinks if necessary.
					try:
						os.unlink(myfile_path)
					except OSError:
						pass

				if mystat is not None:
					if stat.S_ISDIR(mystat.st_mode):
						portage.util.writemsg_level(
							_("!!! Unable to fetch file since "
							"a directory is in the way: \n"
							"!!!   %s\n") % myfile_path,
							level=logging.ERROR, noiselevel=-1)
						return 0

					if mystat.st_size == 0:
						if distdir_writable:
							try:
								os.unlink(myfile_path)
							except OSError:
								pass
					elif distdir_writable:
						if mystat.st_size < fetch_resume_size and \
							mystat.st_size < size:
							# If the file already exists and the size does not
							# match the existing digests, it may be that the
							# user is attempting to update the digest. In this
							# case, the digestgen() function will advise the
							# user to use `ebuild --force foo.ebuild manifest`
							# in order to force the old digests to be replaced.
							# Since the user may want to keep this file, rename
							# it instead of deleting it.
							writemsg(_(">>> Renaming distfile with size "
								"%d (smaller than " "PORTAGE_FETCH_RESU"
								"ME_MIN_SIZE)\n") % mystat.st_size)
							temp_filename = \
								_checksum_failure_temp_file(
								mysettings["DISTDIR"], myfile)
							writemsg_stdout(_("Refetching... "
								"File renamed to '%s'\n\n") % \
								temp_filename, noiselevel=-1)
						elif mystat.st_size >= size:
							temp_filename = \
								_checksum_failure_temp_file(
								mysettings["DISTDIR"], myfile)
							writemsg_stdout(_("Refetching... "
								"File renamed to '%s'\n\n") % \
								temp_filename, noiselevel=-1)

				if distdir_writable and ro_distdirs:
					readonly_file = None
					for x in ro_distdirs:
						filename = os.path.join(x, myfile)
						match, mystat = _check_distfile(
							filename, pruned_digests, eout)
						if match:
							readonly_file = filename
							break
					if readonly_file is not None:
						try:
							os.unlink(myfile_path)
						except OSError as e:
							if e.errno not in (errno.ENOENT, errno.ESTALE):
								raise
							del e
						os.symlink(readonly_file, myfile_path)
						continue

				if fsmirrors and not os.path.exists(myfile_path) and has_space:
					for mydir in fsmirrors:
						mirror_file = os.path.join(mydir, myfile)
						try:
							shutil.copyfile(mirror_file, myfile_path)
							writemsg(_("Local mirror has file: %s\n") % myfile)
							break
						except (IOError, OSError) as e:
							if e.errno not in (errno.ENOENT, errno.ESTALE):
								raise
							del e

				try:
					mystat = os.stat(myfile_path)
				except OSError as e:
					if e.errno not in (errno.ENOENT, errno.ESTALE):
						raise
					del e
				else:
					try:
						apply_secpass_permissions(
							myfile_path, gid=portage_gid, mode=0o664, mask=0o2,
							stat_cached=mystat)
					except portage.exception.PortageException as e:
						if not os.access(myfile_path, os.R_OK):
							writemsg(_("!!! Failed to adjust permissions:"
								" %s\n") % str(e), noiselevel=-1)

					# If the file is empty then it's obviously invalid. Remove
					# the empty file and try to download if possible.
					if mystat.st_size == 0:
						if distdir_writable:
							try:
								os.unlink(myfile_path)
							except EnvironmentError:
								pass
					elif myfile not in mydigests:
						# We don't have a digest, but the file exists.  We must
						# assume that it is fully downloaded.
						continue
					else:
						if mystat.st_size < mydigests[myfile]["size"] and \
							not restrict_fetch:
							fetched = 1 # Try to resume this download.
						elif parallel_fetchonly and \
							mystat.st_size == mydigests[myfile]["size"]:
							eout = portage.output.EOutput()
							eout.quiet = \
								mysettings.get("PORTAGE_QUIET") == "1"
							eout.ebegin(
								"%s size ;-)" % (myfile, ))
							eout.eend(0)
							continue
						else:
							verified_ok, reason = portage.checksum.verify_all(
								myfile_path, mydigests[myfile])
							if not verified_ok:
								writemsg(_("!!! Previously fetched"
									" file: '%s'\n") % myfile, noiselevel=-1)
								writemsg(_("!!! Reason: %s\n") % reason[0],
									noiselevel=-1)
								writemsg(_("!!! Got:      %s\n"
									"!!! Expected: %s\n") % \
									(reason[1], reason[2]), noiselevel=-1)
								if reason[0] == _("Insufficient data for checksum verification"):
									return 0
								if distdir_writable:
									temp_filename = \
										_checksum_failure_temp_file(
										mysettings["DISTDIR"], myfile)
									writemsg_stdout(_("Refetching... "
										"File renamed to '%s'\n\n") % \
										temp_filename, noiselevel=-1)
							else:
								eout = portage.output.EOutput()
								eout.quiet = \
									mysettings.get("PORTAGE_QUIET", None) == "1"
								digests = mydigests.get(myfile)
								if digests:
									digests = list(digests)
									digests.sort()
									eout.ebegin(
										"%s %s ;-)" % (myfile, " ".join(digests)))
									eout.eend(0)
								continue # fetch any remaining files

			# Create a reversed list since that is optimal for list.pop().
			uri_list = filedict[myfile][:]
			uri_list.reverse()
			checksum_failure_count = 0
			tried_locations = set()
			while uri_list:
				loc = uri_list.pop()
				# Eliminate duplicates here in case we've switched to
				# "primaryuri" mode on the fly due to a checksum failure.
				if loc in tried_locations:
					continue
				tried_locations.add(loc)
				if listonly:
					writemsg_stdout(loc+" ", noiselevel=-1)
					continue
				# allow different fetchcommands per protocol
				protocol = loc[0:loc.find("://")]

				missing_file_param = False
				fetchcommand_var = "FETCHCOMMAND_" + protocol.upper()
				fetchcommand = mysettings.get(fetchcommand_var)
				if fetchcommand is None:
					fetchcommand_var = "FETCHCOMMAND"
					fetchcommand = mysettings.get(fetchcommand_var)
					if fetchcommand is None:
						portage.util.writemsg_level(
							_("!!! %s is unset. It should "
							"have been defined in\n!!! %s/make.globals.\n") \
							% (fetchcommand_var,
							portage.const.GLOBAL_CONFIG_PATH),
							level=logging.ERROR, noiselevel=-1)
						return 0
				if "${FILE}" not in fetchcommand:
					portage.util.writemsg_level(
						_("!!! %s does not contain the required ${FILE}"
						" parameter.\n") % fetchcommand_var,
						level=logging.ERROR, noiselevel=-1)
					missing_file_param = True

				resumecommand_var = "RESUMECOMMAND_" + protocol.upper()
				resumecommand = mysettings.get(resumecommand_var)
				if resumecommand is None:
					resumecommand_var = "RESUMECOMMAND"
					resumecommand = mysettings.get(resumecommand_var)
					if resumecommand is None:
						portage.util.writemsg_level(
							_("!!! %s is unset. It should "
							"have been defined in\n!!! %s/make.globals.\n") \
							% (resumecommand_var,
							portage.const.GLOBAL_CONFIG_PATH),
							level=logging.ERROR, noiselevel=-1)
						return 0
				if "${FILE}" not in resumecommand:
					portage.util.writemsg_level(
						_("!!! %s does not contain the required ${FILE}"
						" parameter.\n") % resumecommand_var,
						level=logging.ERROR, noiselevel=-1)
					missing_file_param = True

				if missing_file_param:
					portage.util.writemsg_level(
						_("!!! Refer to the make.conf(5) man page for "
						"information about how to\n!!! correctly specify "
						"FETCHCOMMAND and RESUMECOMMAND.\n"),
						level=logging.ERROR, noiselevel=-1)
					if myfile != os.path.basename(loc):
						return 0

				if not can_fetch:
					if fetched != 2:
						try:
							mysize = os.stat(myfile_path).st_size
						except OSError as e:
							if e.errno not in (errno.ENOENT, errno.ESTALE):
								raise
							del e
							mysize = 0

						if mysize == 0:
							writemsg(_("!!! File %s isn't fetched but unable to get it.\n") % myfile,
								noiselevel=-1)
						elif size is None or size > mysize:
							writemsg(_("!!! File %s isn't fully fetched, but unable to complete it\n") % myfile,
								noiselevel=-1)
						else:
							writemsg(_("!!! File %s is incorrect size, "
								"but unable to retry.\n") % myfile, noiselevel=-1)
						return 0
					else:
						continue

				if fetched != 2 and has_space:
					#we either need to resume or start the download
					if fetched == 1:
						try:
							mystat = os.stat(myfile_path)
						except OSError as e:
							if e.errno not in (errno.ENOENT, errno.ESTALE):
								raise
							del e
							fetched = 0
						else:
							if mystat.st_size < fetch_resume_size:
								writemsg(_(">>> Deleting distfile with size "
									"%d (smaller than " "PORTAGE_FETCH_RESU"
									"ME_MIN_SIZE)\n") % mystat.st_size)
								try:
									os.unlink(myfile_path)
								except OSError as e:
									if e.errno not in \
										(errno.ENOENT, errno.ESTALE):
										raise
									del e
								fetched = 0
					if fetched == 1:
						#resume mode:
						writemsg(_(">>> Resuming download...\n"))
						locfetch=resumecommand
						command_var = resumecommand_var
					else:
						#normal mode:
						locfetch=fetchcommand
						command_var = fetchcommand_var
					writemsg_stdout(_(">>> Downloading '%s'\n") % \
						re.sub(r'//(.+):.+@(.+)/',r'//\1:*password*@\2/', loc))
					variables = {
						"DISTDIR": mysettings["DISTDIR"],
						"URI":     loc,
						"FILE":    myfile
					}

					myfetch = util.shlex_split(locfetch)
					myfetch = [varexpand(x, mydict=variables) for x in myfetch]
					myret = -1
					try:

						myret = _spawn_fetch(mysettings, myfetch)

					finally:
						try:
							apply_secpass_permissions(myfile_path,
								gid=portage_gid, mode=0o664, mask=0o2)
						except portage.exception.FileNotFound as e:
							pass
						except portage.exception.PortageException as e:
							if not os.access(myfile_path, os.R_OK):
								writemsg(_("!!! Failed to adjust permissions:"
									" %s\n") % str(e), noiselevel=-1)

					# If the file is empty then it's obviously invalid.  Don't
					# trust the return value from the fetcher.  Remove the
					# empty file and try to download again.
					try:
						if os.stat(myfile_path).st_size == 0:
							os.unlink(myfile_path)
							fetched = 0
							continue
					except EnvironmentError:
						pass

					if mydigests is not None and myfile in mydigests:
						try:
							mystat = os.stat(myfile_path)
						except OSError as e:
							if e.errno not in (errno.ENOENT, errno.ESTALE):
								raise
							del e
							fetched = 0
						else:

							if stat.S_ISDIR(mystat.st_mode):
								# This can happen if FETCHCOMMAND erroneously
								# contains wget's -P option where it should
								# instead have -O.
								portage.util.writemsg_level(
									_("!!! The command specified in the "
									"%s variable appears to have\n!!! "
									"created a directory instead of a "
									"normal file.\n") % command_var,
									level=logging.ERROR, noiselevel=-1)
								portage.util.writemsg_level(
									_("!!! Refer to the make.conf(5) "
									"man page for information about how "
									"to\n!!! correctly specify "
									"FETCHCOMMAND and RESUMECOMMAND.\n"),
									level=logging.ERROR, noiselevel=-1)
								return 0

							# no exception?  file exists. let digestcheck() report
							# an appropriately for size or checksum errors

							# If the fetcher reported success and the file is
							# too small, it's probably because the digest is
							# bad (upstream changed the distfile).  In this
							# case we don't want to attempt to resume. Show a
							# digest verification failure to that the user gets
							# a clue about what just happened.
							if myret != os.EX_OK and \
								mystat.st_size < mydigests[myfile]["size"]:
								# Fetch failed... Try the next one... Kill 404 files though.
								if (mystat[stat.ST_SIZE]<100000) and (len(myfile)>4) and not ((myfile[-5:]==".html") or (myfile[-4:]==".htm")):
									html404=re.compile("<title>.*(not found|404).*</title>",re.I|re.M)
									if html404.search(codecs.open(
										_unicode_encode(myfile_path,
										encoding=_encodings['fs'], errors='strict'),
										mode='r', encoding=_encodings['content'], errors='replace'
										).read()):
										try:
											os.unlink(mysettings["DISTDIR"]+"/"+myfile)
											writemsg(_(">>> Deleting invalid distfile. (Improper 404 redirect from server.)\n"))
											fetched = 0
											continue
										except (IOError, OSError):
											pass
								fetched = 1
								continue
							if True:
								# File is the correct size--check the checksums for the fetched
								# file NOW, for those users who don't have a stable/continuous
								# net connection. This way we have a chance to try to download
								# from another mirror...
								verified_ok,reason = portage.checksum.verify_all(mysettings["DISTDIR"]+"/"+myfile, mydigests[myfile])
								if not verified_ok:
									print(reason)
									writemsg(_("!!! Fetched file: %s VERIFY FAILED!\n") % myfile,
										noiselevel=-1)
									writemsg(_("!!! Reason: %s\n") % reason[0],
										noiselevel=-1)
									writemsg(_("!!! Got:      %s\n!!! Expected: %s\n") % \
										(reason[1], reason[2]), noiselevel=-1)
									if reason[0] == _("Insufficient data for checksum verification"):
										return 0
									temp_filename = \
										_checksum_failure_temp_file(
										mysettings["DISTDIR"], myfile)
									writemsg_stdout(_("Refetching... "
										"File renamed to '%s'\n\n") % \
										temp_filename, noiselevel=-1)
									fetched=0
									checksum_failure_count += 1
									if checksum_failure_count == \
										checksum_failure_primaryuri:
										# Switch to "primaryuri" mode in order
										# to increase the probablility of
										# of success.
										primaryuris = \
											primaryuri_dict.get(myfile)
										if primaryuris:
											uri_list.extend(
												reversed(primaryuris))
									if checksum_failure_count >= \
										checksum_failure_max_tries:
										break
								else:
									eout = portage.output.EOutput()
									eout.quiet = mysettings.get("PORTAGE_QUIET", None) == "1"
									digests = mydigests.get(myfile)
									if digests:
										eout.ebegin("%s %s ;-)" % \
											(myfile, " ".join(sorted(digests))))
										eout.eend(0)
									fetched=2
									break
					else:
						if not myret:
							fetched=2
							break
						elif mydigests!=None:
							writemsg(_("No digest file available and download failed.\n\n"),
								noiselevel=-1)
		finally:
			if use_locks and file_lock:
				portage.locks.unlockfile(file_lock)

		if listonly:
			writemsg_stdout("\n", noiselevel=-1)
		if fetched != 2:
			if restrict_fetch and not restrict_fetch_msg:
				restrict_fetch_msg = True
				msg = _("\n!!! %s/%s"
					" has fetch restriction turned on.\n"
					"!!! This probably means that this "
					"ebuild's files must be downloaded\n"
					"!!! manually.  See the comments in"
					" the ebuild for more information.\n\n") % \
					(mysettings["CATEGORY"], mysettings["PF"])
				portage.util.writemsg_level(msg,
					level=logging.ERROR, noiselevel=-1)
				have_builddir = "PORTAGE_BUILDDIR" in mysettings and \
					os.path.isdir(mysettings["PORTAGE_BUILDDIR"])

				global_tmpdir = mysettings["PORTAGE_TMPDIR"]
				private_tmpdir = None
				if not parallel_fetchonly and not have_builddir:
					# When called by digestgen(), it's normal that
					# PORTAGE_BUILDDIR doesn't exist. It's helpful
					# to show the pkg_nofetch output though, so go
					# ahead and create a temporary PORTAGE_BUILDDIR.
					# Use a temporary config instance to avoid altering
					# the state of the one that's been passed in.
					mysettings = config(clone=mysettings)
					from tempfile import mkdtemp
					try:
						private_tmpdir = mkdtemp("", "._portage_fetch_.",
							global_tmpdir)
					except OSError as e:
						if e.errno != portage.exception.PermissionDenied.errno:
							raise
						raise portage.exception.PermissionDenied(global_tmpdir)
					mysettings["PORTAGE_TMPDIR"] = private_tmpdir
					mysettings.backup_changes("PORTAGE_TMPDIR")
					debug = mysettings.get("PORTAGE_DEBUG") == "1"
					portage.doebuild_environment(mysettings["EBUILD"], "fetch",
						mysettings["ROOT"], mysettings, debug, 1, None)
					prepare_build_dirs(mysettings["ROOT"], mysettings, 0)
					have_builddir = True

				if not parallel_fetchonly and have_builddir:
					# To spawn pkg_nofetch requires PORTAGE_BUILDDIR for
					# ensuring sane $PWD (bug #239560) and storing elog
					# messages. Therefore, calling code needs to ensure that
					# PORTAGE_BUILDDIR is already clean and locked here.

					# All the pkg_nofetch goes to stderr since it's considered
					# to be an error message.
					fd_pipes = {
						0 : sys.stdin.fileno(),
						1 : sys.stderr.fileno(),
						2 : sys.stderr.fileno(),
					}

					ebuild_phase = mysettings.get("EBUILD_PHASE")
					try:
						mysettings["EBUILD_PHASE"] = "nofetch"
						spawn(_shell_quote(EBUILD_SH_BINARY) + \
							" nofetch", mysettings, fd_pipes=fd_pipes)
					finally:
						if ebuild_phase is None:
							mysettings.pop("EBUILD_PHASE", None)
						else:
							mysettings["EBUILD_PHASE"] = ebuild_phase
						if private_tmpdir is not None:
							shutil.rmtree(private_tmpdir)

			elif restrict_fetch:
				pass
			elif listonly:
				pass
			elif not filedict[myfile]:
				writemsg(_("Warning: No mirrors available for file"
					" '%s'\n") % (myfile), noiselevel=-1)
			else:
				writemsg(_("!!! Couldn't download '%s'. Aborting.\n") % myfile,
					noiselevel=-1)

			if listonly:
				continue
			elif fetchonly:
				failed_files.add(myfile)
				continue
			return 0
	if failed_files:
		return 0
	return 1

def digestgen(myarchives, mysettings, overwrite=1, manifestonly=0, myportdb=None):
	"""
	Generates a digest file if missing.  Assumes all files are available.
	DEPRECATED: this now only is a compability wrapper for 
	            portage.manifest.Manifest()
	NOTE: manifestonly and overwrite are useless with manifest2 and
	      are therefore ignored."""
	if myportdb is None:
		writemsg("Warning: myportdb not specified to digestgen\n")
		global portdb
		myportdb = portdb
	global _doebuild_manifest_exempt_depend
	try:
		_doebuild_manifest_exempt_depend += 1
		distfiles_map = {}
		fetchlist_dict = FetchlistDict(mysettings["O"], mysettings, myportdb)
		for cpv in fetchlist_dict:
			try:
				for myfile in fetchlist_dict[cpv]:
					distfiles_map.setdefault(myfile, []).append(cpv)
			except portage.exception.InvalidDependString as e:
				writemsg("!!! %s\n" % str(e), noiselevel=-1)
				del e
				return 0
		mytree = os.path.dirname(os.path.dirname(mysettings["O"]))
		manifest1_compat = False
		mf = Manifest(mysettings["O"], mysettings["DISTDIR"],
			fetchlist_dict=fetchlist_dict, manifest1_compat=manifest1_compat)
		# Don't require all hashes since that can trigger excessive
		# fetches when sufficient digests already exist.  To ease transition
		# while Manifest 1 is being removed, only require hashes that will
		# exist before and after the transition.
		required_hash_types = set()
		required_hash_types.add("size")
		required_hash_types.add(portage.const.MANIFEST2_REQUIRED_HASH)
		dist_hashes = mf.fhashdict.get("DIST", {})

		# To avoid accidental regeneration of digests with the incorrect
		# files (such as partially downloaded files), trigger the fetch
		# code if the file exists and it's size doesn't match the current
		# manifest entry. If there really is a legitimate reason for the
		# digest to change, `ebuild --force digest` can be used to avoid
		# triggering this code (or else the old digests can be manually
		# removed from the Manifest).
		missing_files = []
		for myfile in distfiles_map:
			myhashes = dist_hashes.get(myfile)
			if not myhashes:
				try:
					st = os.stat(os.path.join(mysettings["DISTDIR"], myfile))
				except OSError:
					st = None
				if st is None or st.st_size == 0:
					missing_files.append(myfile)
				continue
			size = myhashes.get("size")

			try:
				st = os.stat(os.path.join(mysettings["DISTDIR"], myfile))
			except OSError as e:
				if e.errno != errno.ENOENT:
					raise
				del e
				if size == 0:
					missing_files.append(myfile)
					continue
				if required_hash_types.difference(myhashes):
					missing_files.append(myfile)
					continue
			else:
				if st.st_size == 0 or size is not None and size != st.st_size:
					missing_files.append(myfile)
					continue

		if missing_files:
				mytree = os.path.realpath(os.path.dirname(
					os.path.dirname(mysettings["O"])))
				fetch_settings = config(clone=mysettings)
				debug = mysettings.get("PORTAGE_DEBUG") == "1"
				for myfile in missing_files:
					uris = set()
					for cpv in distfiles_map[myfile]:
						myebuild = os.path.join(mysettings["O"],
							catsplit(cpv)[1] + ".ebuild")
						# for RESTRICT=fetch, mirror, etc...
						doebuild_environment(myebuild, "fetch",
							mysettings["ROOT"], fetch_settings,
							debug, 1, myportdb)
						uris.update(myportdb.getFetchMap(
							cpv, mytree=mytree)[myfile])

					fetch_settings["A"] = myfile # for use by pkg_nofetch()

					try:
						st = os.stat(os.path.join(
							mysettings["DISTDIR"],myfile))
					except OSError:
						st = None

					if not fetch({myfile : uris}, fetch_settings):
						writemsg(_("!!! Fetch failed for %s, can't update "
							"Manifest\n") % myfile, noiselevel=-1)
						if myfile in dist_hashes and \
							st is not None and st.st_size > 0:
							# stat result is obtained before calling fetch(),
							# since fetch may rename the existing file if the
							# digest does not match.
							writemsg(_("!!! If you would like to "
								"forcefully replace the existing "
								"Manifest entry\n!!! for %s, use "
								"the following command:\n") % myfile + \
								"!!!    " + colorize("INFORM",
								"ebuild --force %s manifest" % \
								os.path.basename(myebuild)) + "\n",
								noiselevel=-1)
						return 0
		writemsg_stdout(_(">>> Creating Manifest for %s\n") % mysettings["O"])
		try:
			mf.create(requiredDistfiles=myarchives,
				assumeDistHashesSometimes=True,
				assumeDistHashesAlways=(
				"assume-digests" in mysettings.features))
		except portage.exception.FileNotFound as e:
			writemsg(_("!!! File %s doesn't exist, can't update "
				"Manifest\n") % e, noiselevel=-1)
			return 0
		except portage.exception.PortagePackageException as e:
			writemsg(("!!! %s\n") % (e,), noiselevel=-1)
			return 0
		try:
			mf.write(sign=False)
		except portage.exception.PermissionDenied as e:
			writemsg(_("!!! Permission Denied: %s\n") % (e,), noiselevel=-1)
			return 0
		if "assume-digests" not in mysettings.features:
			distlist = list(mf.fhashdict.get("DIST", {}))
			distlist.sort()
			auto_assumed = []
			for filename in distlist:
				if not os.path.exists(
					os.path.join(mysettings["DISTDIR"], filename)):
					auto_assumed.append(filename)
			if auto_assumed:
				mytree = os.path.realpath(
					os.path.dirname(os.path.dirname(mysettings["O"])))
				cp = os.path.sep.join(mysettings["O"].split(os.path.sep)[-2:])
				pkgs = myportdb.cp_list(cp, mytree=mytree)
				pkgs.sort()
				writemsg_stdout("  digest.assumed" + portage.output.colorize("WARN",
					str(len(auto_assumed)).rjust(18)) + "\n")
				for pkg_key in pkgs:
					fetchlist = myportdb.getFetchMap(pkg_key, mytree=mytree)
					pv = pkg_key.split("/")[1]
					for filename in auto_assumed:
						if filename in fetchlist:
							writemsg_stdout(
								"   %s::%s\n" % (pv, filename))
		return 1
	finally:
		_doebuild_manifest_exempt_depend -= 1

def digestParseFile(myfilename, mysettings=None):
	"""(filename) -- Parses a given file for entries matching:
	<checksumkey> <checksum_hex_string> <filename> <filesize>
	Ignores lines that don't start with a valid checksum identifier
	and returns a dict with the filenames as keys and {checksumkey:checksum}
	as the values.
	DEPRECATED: this function is now only a compability wrapper for
	            portage.manifest.Manifest()."""

	mysplit = myfilename.split(os.sep)
	if mysplit[-2] == "files" and mysplit[-1].startswith("digest-"):
		pkgdir = os.sep + os.sep.join(mysplit[:-2]).strip(os.sep)
	elif mysplit[-1] == "Manifest":
		pkgdir = os.sep + os.sep.join(mysplit[:-1]).strip(os.sep)

	if mysettings is None:
		global settings
		mysettings = config(clone=settings)

	return Manifest(pkgdir, mysettings["DISTDIR"]).getDigests()

def digestcheck(myfiles, mysettings, strict=0, justmanifest=0):
	"""Verifies checksums.  Assumes all files have been downloaded.
	DEPRECATED: this is now only a compability wrapper for 
	            portage.manifest.Manifest()."""
	if mysettings.get("EBUILD_SKIP_MANIFEST") == "1":
		return 1
	pkgdir = mysettings["O"]
	manifest_path = os.path.join(pkgdir, "Manifest")
	if not os.path.exists(manifest_path):
		writemsg(_("!!! Manifest file not found: '%s'\n") % manifest_path,
			noiselevel=-1)
		if strict:
			return 0
		else:
			return 1
	mf = Manifest(pkgdir, mysettings["DISTDIR"])
	manifest_empty = True
	for d in mf.fhashdict.values():
		if d:
			manifest_empty = False
			break
	if manifest_empty:
		writemsg(_("!!! Manifest is empty: '%s'\n") % manifest_path,
			noiselevel=-1)
		if strict:
			return 0
		else:
			return 1
	eout = portage.output.EOutput()
	eout.quiet = mysettings.get("PORTAGE_QUIET", None) == "1"
	try:
		if strict and "PORTAGE_PARALLEL_FETCHONLY" not in mysettings:
			eout.ebegin(_("checking ebuild checksums ;-)"))
			mf.checkTypeHashes("EBUILD")
			eout.eend(0)
			eout.ebegin(_("checking auxfile checksums ;-)"))
			mf.checkTypeHashes("AUX")
			eout.eend(0)
			eout.ebegin(_("checking miscfile checksums ;-)"))
			mf.checkTypeHashes("MISC", ignoreMissingFiles=True)
			eout.eend(0)
		for f in myfiles:
			eout.ebegin(_("checking %s ;-)") % f)
			ftype = mf.findFile(f)
			if ftype is None:
				raise KeyError(f)
			mf.checkFileHashes(ftype, f)
			eout.eend(0)
	except KeyError as e:
		eout.eend(1)
		writemsg(_("\n!!! Missing digest for %s\n") % str(e), noiselevel=-1)
		return 0
	except portage.exception.FileNotFound as e:
		eout.eend(1)
		writemsg(_("\n!!! A file listed in the Manifest could not be found: %s\n") % str(e),
			noiselevel=-1)
		return 0
	except portage.exception.DigestException as e:
		eout.eend(1)
		writemsg(_("\n!!! Digest verification failed:\n"), noiselevel=-1)
		writemsg("!!! %s\n" % e.value[0], noiselevel=-1)
		writemsg(_("!!! Reason: %s\n") % e.value[1], noiselevel=-1)
		writemsg(_("!!! Got: %s\n") % e.value[2], noiselevel=-1)
		writemsg(_("!!! Expected: %s\n") % e.value[3], noiselevel=-1)
		return 0
	# Make sure that all of the ebuilds are actually listed in the Manifest.
	glep55 = 'parse-eapi-glep-55' in mysettings.features
	for f in os.listdir(pkgdir):
		pf = None
		if glep55:
			pf, eapi = _split_ebuild_name_glep55(f)
		elif f[-7:] == '.ebuild':
			pf = f[:-7]
		if pf is not None and not mf.hasFile("EBUILD", f):
			writemsg(_("!!! A file is not listed in the Manifest: '%s'\n") % \
				os.path.join(pkgdir, f), noiselevel=-1)
			if strict:
				return 0
	""" epatch will just grab all the patches out of a directory, so we have to
	make sure there aren't any foreign files that it might grab."""
	filesdir = os.path.join(pkgdir, "files")

	for parent, dirs, files in os.walk(filesdir):
		try:
			parent = _unicode_decode(parent,
				encoding=_encodings['fs'], errors='strict')
		except UnicodeDecodeError:
			parent = _unicode_decode(parent,
				encoding=_encodings['fs'], errors='replace')
			writemsg(_("!!! Path contains invalid "
				"character(s) for encoding '%s': '%s'") \
				% (_encodings['fs'], parent), noiselevel=-1)
			if strict:
				return 0
			continue
		for d in dirs:
			d_bytes = d
			try:
				d = _unicode_decode(d,
					encoding=_encodings['fs'], errors='strict')
			except UnicodeDecodeError:
				d = _unicode_decode(d,
					encoding=_encodings['fs'], errors='replace')
				writemsg(_("!!! Path contains invalid "
					"character(s) for encoding '%s': '%s'") \
					% (_encodings['fs'], os.path.join(parent, d)),
					noiselevel=-1)
				if strict:
					return 0
				dirs.remove(d_bytes)
				continue
			if d.startswith(".") or d == "CVS":
				dirs.remove(d_bytes)
		for f in files:
			try:
				f = _unicode_decode(f,
					encoding=_encodings['fs'], errors='strict')
			except UnicodeDecodeError:
				f = _unicode_decode(f,
					encoding=_encodings['fs'], errors='replace')
				if f.startswith("."):
					continue
				f = os.path.join(parent, f)[len(filesdir) + 1:]
				writemsg(_("!!! File name contains invalid "
					"character(s) for encoding '%s': '%s'") \
					% (_encodings['fs'], f), noiselevel=-1)
				if strict:
					return 0
				continue
			if f.startswith("."):
				continue
			f = os.path.join(parent, f)[len(filesdir) + 1:]
			file_type = mf.findFile(f)
			if file_type != "AUX" and not f.startswith("digest-"):
				writemsg(_("!!! A file is not listed in the Manifest: '%s'\n") % \
					os.path.join(filesdir, f), noiselevel=-1)
				if strict:
					return 0
	return 1

# parse actionmap to spawn ebuild with the appropriate args
def spawnebuild(mydo, actionmap, mysettings, debug, alwaysdep=0,
	logfile=None, fd_pipes=None, returnpid=False):
	if not returnpid and \
		(alwaysdep or "noauto" not in mysettings.features):
		# process dependency first
		if "dep" in actionmap[mydo]:
			retval = spawnebuild(actionmap[mydo]["dep"], actionmap,
				mysettings, debug, alwaysdep=alwaysdep, logfile=logfile,
				fd_pipes=fd_pipes, returnpid=returnpid)
			if retval:
				return retval

	eapi = mysettings["EAPI"]

	if mydo == "configure" and eapi in ("0", "1"):
		return os.EX_OK

	if mydo == "prepare" and eapi in ("0", "1"):
		return os.EX_OK

	if mydo == "pretend" and eapi in ("0", "1", "2"):
		return os.EX_OK

	kwargs = actionmap[mydo]["args"]
	mysettings["EBUILD_PHASE"] = mydo
	_doebuild_exit_status_unlink(
		mysettings.get("EBUILD_EXIT_STATUS_FILE"))

	try:
		phase_retval = spawn(actionmap[mydo]["cmd"] % mydo,
			mysettings, debug=debug, logfile=logfile,
			fd_pipes=fd_pipes, returnpid=returnpid, **kwargs)
	finally:
		mysettings["EBUILD_PHASE"] = ""

	if returnpid:
		return phase_retval

	msg = _doebuild_exit_status_check(mydo, mysettings)
	if msg:
		if phase_retval == os.EX_OK:
			phase_retval = 1
		from textwrap import wrap
		from portage.elog.messages import eerror
		for l in wrap(msg, 72):
			eerror(l, phase=mydo, key=mysettings.mycpv)

	_post_phase_userpriv_perms(mysettings)
	if mydo == "install":
		_check_build_log(mysettings)
		if phase_retval == os.EX_OK:
			_post_src_install_chost_fix(mysettings)
			phase_retval = _post_src_install_checks(mysettings)

	if mydo == "test" and phase_retval != os.EX_OK and \
		"test-fail-continue" in mysettings.features:
		phase_retval = os.EX_OK

	return phase_retval

_post_phase_cmds = {

	"install" : [
		"install_qa_check",
		"install_symlink_html_docs"],

	"preinst" : [
		"preinst_bsdflags",
		"preinst_sfperms",
		"preinst_selinux_labels",
		"preinst_suid_scan",
		"preinst_mask"],

	"postinst" : [
		"postinst_bsdflags"]
}

def _post_phase_userpriv_perms(mysettings):
	if "userpriv" in mysettings.features and secpass >= 2:
		""" Privileged phases may have left files that need to be made
		writable to a less privileged user."""
		apply_recursive_permissions(mysettings["T"],
			uid=portage_uid, gid=portage_gid, dirmode=0o70, dirmask=0,
			filemode=0o60, filemask=0)

def _post_src_install_checks(mysettings):
	_post_src_install_uid_fix(mysettings)
	global _post_phase_cmds
	retval = _spawn_misc_sh(mysettings, _post_phase_cmds["install"])
	if retval != os.EX_OK:
		writemsg(_("!!! install_qa_check failed; exiting.\n"),
			noiselevel=-1)
	return retval

def _check_build_log(mysettings, out=None):
	"""
	Search the content of $PORTAGE_LOG_FILE if it exists
	and generate the following QA Notices when appropriate:

	  * Automake "maintainer mode"
	  * command not found
	  * Unrecognized configure options
	"""
	logfile = mysettings.get("PORTAGE_LOG_FILE")
	if logfile is None:
		return
	try:
		f = codecs.open(_unicode_encode(logfile,
			encoding=_encodings['fs'], errors='strict'),
			mode='r', encoding=_encodings['content'], errors='replace')
	except EnvironmentError:
		return

	am_maintainer_mode = []
	bash_command_not_found = []
	bash_command_not_found_re = re.compile(
		r'(.*): line (\d*): (.*): command not found$')
	command_not_found_exclude_re = re.compile(r'/configure: line ')
	helper_missing_file = []
	helper_missing_file_re = re.compile(
		r'^!!! (do|new).*: .* does not exist$')

	configure_opts_warn = []
	configure_opts_warn_re = re.compile(
		r'^configure: WARNING: [Uu]nrecognized options: ')

	# Exclude output from dev-libs/yaz-3.0.47 which looks like this:
	#
	#Configuration:
	#  Automake:                   ${SHELL} /var/tmp/portage/dev-libs/yaz-3.0.47/work/yaz-3.0.47/config/missing --run automake-1.10
	am_maintainer_mode_re = re.compile(r'/missing --run ')
	am_maintainer_mode_exclude_re = \
		re.compile(r'(/missing --run (autoheader|makeinfo)|^\s*Automake:\s)')

	make_jobserver_re = \
		re.compile(r'g?make\[\d+\]: warning: jobserver unavailable:')
	make_jobserver = []

	try:
		for line in f:
			if am_maintainer_mode_re.search(line) is not None and \
				am_maintainer_mode_exclude_re.search(line) is None:
				am_maintainer_mode.append(line.rstrip("\n"))

			if bash_command_not_found_re.match(line) is not None and \
				command_not_found_exclude_re.search(line) is None:
				bash_command_not_found.append(line.rstrip("\n"))

			if helper_missing_file_re.match(line) is not None:
				helper_missing_file.append(line.rstrip("\n"))

			if configure_opts_warn_re.match(line) is not None:
				configure_opts_warn.append(line.rstrip("\n"))

			if make_jobserver_re.match(line) is not None:
				make_jobserver.append(line.rstrip("\n"))

	finally:
		f.close()

	from portage.elog.messages import eqawarn
	def _eqawarn(lines):
		for line in lines:
			eqawarn(line, phase="install", key=mysettings.mycpv, out=out)
	from textwrap import wrap
	wrap_width = 70

	if am_maintainer_mode:
		msg = [_("QA Notice: Automake \"maintainer mode\" detected:")]
		msg.append("")
		msg.extend("\t" + line for line in am_maintainer_mode)
		msg.append("")
		msg.extend(wrap(_(
			"If you patch Makefile.am, "
			"configure.in,  or configure.ac then you "
			"should use autotools.eclass and "
			"eautomake or eautoreconf. Exceptions "
			"are limited to system packages "
			"for which it is impossible to run "
			"autotools during stage building. "
			"See http://www.gentoo.org/p"
			"roj/en/qa/autofailure.xml for more information."),
			wrap_width))
		_eqawarn(msg)

	if bash_command_not_found:
		msg = [_("QA Notice: command not found:")]
		msg.append("")
		msg.extend("\t" + line for line in bash_command_not_found)
		_eqawarn(msg)

	if helper_missing_file:
		msg = [_("QA Notice: file does not exist:")]
		msg.append("")
		msg.extend("\t" + line[4:] for line in helper_missing_file)
		_eqawarn(msg)

	if configure_opts_warn:
		msg = [_("QA Notice: Unrecognized configure options:")]
		msg.append("")
		msg.extend("\t" + line for line in configure_opts_warn)
		_eqawarn(msg)

	if make_jobserver:
		msg = [_("QA Notice: make jobserver unavailable:")]
		msg.append("")
		msg.extend("\t" + line for line in make_jobserver)
		_eqawarn(msg)

def _post_src_install_chost_fix(settings):
	"""
	It's possible that the ebuild has changed the
	CHOST variable, so revert it to the initial
	setting.
	"""
	chost = settings.get('CHOST')
	if chost:
		write_atomic(os.path.join(settings['PORTAGE_BUILDDIR'],
			'build-info', 'CHOST'), chost + '\n')

def _post_src_install_uid_fix(mysettings, out=None):
	"""
	Files in $D with user and group bits that match the "portage"
	user or group are automatically mapped to PORTAGE_INST_UID and
	PORTAGE_INST_GID if necessary. The chown system call may clear
	S_ISUID and S_ISGID bits, so those bits are restored if
	necessary.
	"""

	os = _os_merge

	inst_uid = int(mysettings["PORTAGE_INST_UID"])
	inst_gid = int(mysettings["PORTAGE_INST_GID"])

	if bsd_chflags:
		# Temporarily remove all of the flags in order to avoid EPERM errors.
		os.system("mtree -c -p %s -k flags > %s" % \
			(_shell_quote(mysettings["D"]),
			_shell_quote(os.path.join(mysettings["T"], "bsdflags.mtree"))))
		os.system("chflags -R noschg,nouchg,nosappnd,nouappnd %s" % \
			(_shell_quote(mysettings["D"]),))
		os.system("chflags -R nosunlnk,nouunlnk %s 2>/dev/null" % \
			(_shell_quote(mysettings["D"]),))

	destdir = mysettings["D"]
	unicode_errors = []

	while True:

		unicode_error = False
		size = 0
		counted_inodes = set()

		for parent, dirs, files in os.walk(destdir):
			try:
				parent = _unicode_decode(parent,
					encoding=_encodings['merge'], errors='strict')
			except UnicodeDecodeError:
				new_parent = _unicode_decode(parent,
					encoding=_encodings['merge'], errors='replace')
				new_parent = _unicode_encode(new_parent,
					encoding=_encodings['merge'], errors='backslashreplace')
				new_parent = _unicode_decode(new_parent,
					encoding=_encodings['merge'], errors='replace')
				os.rename(parent, new_parent)
				unicode_error = True
				unicode_errors.append(new_parent[len(destdir):])
				break

			for fname in chain(dirs, files):
				try:
					fname = _unicode_decode(fname,
						encoding=_encodings['merge'], errors='strict')
				except UnicodeDecodeError:
					fpath = _os.path.join(
						parent.encode(_encodings['merge']), fname)
					new_fname = _unicode_decode(fname,
						encoding=_encodings['merge'], errors='replace')
					new_fname = _unicode_encode(new_fname,
						encoding=_encodings['merge'], errors='backslashreplace')
					new_fname = _unicode_decode(new_fname,
						encoding=_encodings['merge'], errors='replace')
					new_fpath = os.path.join(parent, new_fname)
					os.rename(fpath, new_fpath)
					unicode_error = True
					unicode_errors.append(new_fpath[len(destdir):])
					fname = new_fname
					fpath = new_fpath
				else:
					fpath = os.path.join(parent, fname)

				mystat = os.lstat(fpath)
				if stat.S_ISREG(mystat.st_mode) and \
					mystat.st_ino not in counted_inodes:
					counted_inodes.add(mystat.st_ino)
					size += mystat.st_size
				if mystat.st_uid != portage_uid and \
					mystat.st_gid != portage_gid:
					continue
				myuid = -1
				mygid = -1
				if mystat.st_uid == portage_uid:
					myuid = inst_uid
				if mystat.st_gid == portage_gid:
					mygid = inst_gid
				apply_secpass_permissions(
					_unicode_encode(fpath, encoding=_encodings['merge']),
					uid=myuid, gid=mygid,
					mode=mystat.st_mode, stat_cached=mystat,
					follow_links=False)

			if unicode_error:
				break

		if not unicode_error:
			break

	if unicode_errors:
		from portage.elog.messages import eerror
		for l in _merge_unicode_error(unicode_errors):
			eerror(l, phase='install', key=mysettings.mycpv, out=out)

	open(_unicode_encode(os.path.join(mysettings['PORTAGE_BUILDDIR'],
		'build-info', 'SIZE')), 'w').write(str(size) + '\n')

	if bsd_chflags:
		# Restore all of the flags saved above.
		os.system("mtree -e -p %s -U -k flags < %s > /dev/null" % \
			(_shell_quote(mysettings["D"]),
			_shell_quote(os.path.join(mysettings["T"], "bsdflags.mtree"))))

def _merge_unicode_error(errors):
	from textwrap import wrap
	lines = []

	msg = _("This package installs one or more file names containing "
		"characters that do not match your current locale "
		"settings. The current setting for filesystem encoding is '%s'.") \
		% _encodings['merge']
	lines.extend(wrap(msg, 72))

	lines.append("")
	errors.sort()
	lines.extend("\t" + x for x in errors)
	lines.append("")

	if _encodings['merge'].lower().replace('_', '').replace('-', '') != 'utf8':
		msg = _("For best results, UTF-8 encoding is recommended. See "
			"the Gentoo Linux Localization Guide for instructions "
			"about how to configure your locale for UTF-8 encoding:")
		lines.extend(wrap(msg, 72))
		lines.append("")
		lines.append("\t" + \
			"http://www.gentoo.org/doc/en/guide-localization.xml")
		lines.append("")

	return lines

def _post_pkg_preinst_cmd(mysettings):
	"""
	Post phase logic and tasks that have been factored out of
	ebuild.sh. Call preinst_mask last so that INSTALL_MASK can
	can be used to wipe out any gmon.out files created during
	previous functions (in case any tools were built with -pg
	in CFLAGS).
	"""

	portage_bin_path = mysettings["PORTAGE_BIN_PATH"]
	misc_sh_binary = os.path.join(portage_bin_path,
		os.path.basename(MISC_SH_BINARY))

	mysettings["EBUILD_PHASE"] = ""
	global _post_phase_cmds
	myargs = [_shell_quote(misc_sh_binary)] + _post_phase_cmds["preinst"]

	return myargs

def _post_pkg_postinst_cmd(mysettings):
	"""
	Post phase logic and tasks that have been factored out of
	build.sh.
	"""

	portage_bin_path = mysettings["PORTAGE_BIN_PATH"]
	misc_sh_binary = os.path.join(portage_bin_path,
		os.path.basename(MISC_SH_BINARY))

	mysettings["EBUILD_PHASE"] = ""
	global _post_phase_cmds
	myargs = [_shell_quote(misc_sh_binary)] + _post_phase_cmds["postinst"]

	return myargs

def _spawn_misc_sh(mysettings, commands, **kwargs):
	"""
	@param mysettings: the ebuild config
	@type mysettings: config
	@param commands: a list of function names to call in misc-functions.sh
	@type commands: list
	@rtype: int
	@returns: the return value from the spawn() call
	"""

	# Note: PORTAGE_BIN_PATH may differ from the global
	# constant when portage is reinstalling itself.
	portage_bin_path = mysettings["PORTAGE_BIN_PATH"]
	misc_sh_binary = os.path.join(portage_bin_path,
		os.path.basename(MISC_SH_BINARY))
	mycommand = " ".join([_shell_quote(misc_sh_binary)] + commands)
	_doebuild_exit_status_unlink(
		mysettings.get("EBUILD_EXIT_STATUS_FILE"))
	debug = mysettings.get("PORTAGE_DEBUG") == "1"
	logfile = mysettings.get("PORTAGE_LOG_FILE")
	mydo = mysettings["EBUILD_PHASE"]
	try:
		rval = spawn(mycommand, mysettings, debug=debug,
			logfile=logfile, **kwargs)
	finally:
		pass

	msg = _doebuild_exit_status_check(mydo, mysettings)
	if msg:
		if rval == os.EX_OK:
			rval = 1
		from textwrap import wrap
		from portage.elog.messages import eerror
		for l in wrap(msg, 72):
			eerror(l, phase=mydo, key=mysettings.mycpv)

	return rval

_testing_eapis = frozenset(["3_pre1"])
_deprecated_eapis = frozenset(["2_pre3", "2_pre2", "2_pre1"])

def _eapi_is_deprecated(eapi):
	return eapi in _deprecated_eapis

def eapi_is_supported(eapi):
	eapi = str(eapi).strip()

	if _eapi_is_deprecated(eapi):
		return True

	if eapi in _testing_eapis:
		return True

	try:
		eapi = int(eapi)
	except ValueError:
		eapi = -1
	if eapi < 0:
		return False
	return eapi <= portage.const.EAPI

# Generally, it's best not to assume that cache entries for unsupported EAPIs
# can be validated. However, the current package manager specification does not
# guarantee that the EAPI can be parsed without sourcing the ebuild, so
# it's too costly to discard existing cache entries for unsupported EAPIs.
# Therefore, by default, assume that cache entries for unsupported EAPIs can be
# validated. If FEATURES=parse-eapi-* is enabled, this assumption is discarded
# since the EAPI can be determined without the incurring the cost of sourcing
# the ebuild.
_validate_cache_for_unsupported_eapis = True

_parse_eapi_ebuild_head_re = re.compile(r'^EAPI=[\'"]?([^\'"#]*)')
_parse_eapi_ebuild_head_max_lines = 30

def _parse_eapi_ebuild_head(f):
	count = 0
	for line in f:
		m = _parse_eapi_ebuild_head_re.match(line)
		if m is not None:
			return m.group(1).strip()
		count += 1
		if count >= _parse_eapi_ebuild_head_max_lines:
			break
	return '0'

# True when FEATURES=parse-eapi-glep-55 is enabled.
_glep_55_enabled = False

_split_ebuild_name_glep55_re = re.compile(r'^(.*)\.ebuild(-([^.]+))?$')

def _split_ebuild_name_glep55(name):
	"""
	@returns: (pkg-ver-rev, eapi)
	"""
	m = _split_ebuild_name_glep55_re.match(name)
	if m is None:
		return (None, None)
	return (m.group(1), m.group(3))

def doebuild_environment(myebuild, mydo, myroot, mysettings, debug, use_cache, mydbapi):

	ebuild_path = os.path.abspath(myebuild)
	pkg_dir     = os.path.dirname(ebuild_path)

	if "CATEGORY" in mysettings.configdict["pkg"]:
		cat = mysettings.configdict["pkg"]["CATEGORY"]
	else:
		cat = os.path.basename(normalize_path(os.path.join(pkg_dir, "..")))

	eapi = None
	if 'parse-eapi-glep-55' in mysettings.features:
		mypv, eapi = portage._split_ebuild_name_glep55(
			os.path.basename(myebuild))
	else:
		mypv = os.path.basename(ebuild_path)[:-7]

	mycpv = cat+"/"+mypv
	mysplit = versions._pkgsplit(mypv)
	if mysplit is None:
		raise portage.exception.IncorrectParameter(
			_("Invalid ebuild path: '%s'") % myebuild)

	# Make a backup of PORTAGE_TMPDIR prior to calling config.reset()
	# so that the caller can override it.
	tmpdir = mysettings["PORTAGE_TMPDIR"]

	if mydo == 'depend':
		if mycpv != mysettings.mycpv:
			# Don't pass in mydbapi here since the resulting aux_get
			# call would lead to infinite 'depend' phase recursion.
			mysettings.setcpv(mycpv)
	else:
		# If IUSE isn't in configdict['pkg'], it means that setcpv()
		# hasn't been called with the mydb argument, so we have to
		# call it here (portage code always calls setcpv properly,
		# but api consumers might not).
		if mycpv != mysettings.mycpv or \
			'IUSE' not in mysettings.configdict['pkg']:
			# Reload env.d variables and reset any previous settings.
			mysettings.reload()
			mysettings.reset()
			mysettings.setcpv(mycpv, mydb=mydbapi)

	# config.reset() might have reverted a change made by the caller,
	# so restore it to it's original value.
	mysettings["PORTAGE_TMPDIR"] = tmpdir

	mysettings.pop("EBUILD_PHASE", None) # remove from backupenv
	mysettings["EBUILD_PHASE"] = mydo

	mysettings["PORTAGE_MASTER_PID"] = str(os.getpid())

	# We are disabling user-specific bashrc files.
	mysettings["BASH_ENV"] = INVALID_ENV_FILE

	if debug: # Otherwise it overrides emerge's settings.
		# We have no other way to set debug... debug can't be passed in
		# due to how it's coded... Don't overwrite this so we can use it.
		mysettings["PORTAGE_DEBUG"] = "1"

	mysettings["ROOT"]     = myroot
	mysettings["STARTDIR"] = getcwd()
	mysettings["EBUILD"]   = ebuild_path
	mysettings["O"]        = pkg_dir
	mysettings.configdict["pkg"]["CATEGORY"] = cat
	mysettings["FILESDIR"] = pkg_dir+"/files"
	mysettings["PF"]       = mypv

	if hasattr(mydbapi, '_repo_info'):
		mytree = os.path.dirname(os.path.dirname(pkg_dir))
		repo_info = mydbapi._repo_info[mytree]
		mysettings['PORTDIR'] = repo_info.portdir
		mysettings['PORTDIR_OVERLAY'] = repo_info.portdir_overlay

	mysettings["PORTDIR"] = os.path.realpath(mysettings["PORTDIR"])
	mysettings["DISTDIR"] = os.path.realpath(mysettings["DISTDIR"])
	mysettings["RPMDIR"]  = os.path.realpath(mysettings["RPMDIR"])

	mysettings["ECLASSDIR"]   = mysettings["PORTDIR"]+"/eclass"
	mysettings["SANDBOX_LOG"] = mycpv.replace("/", "_-_")

	mysettings["PROFILE_PATHS"] = "\n".join(mysettings.profiles)
	mysettings["P"]  = mysplit[0]+"-"+mysplit[1]
	mysettings["PN"] = mysplit[0]
	mysettings["PV"] = mysplit[1]
	mysettings["PR"] = mysplit[2]

	if portage.util.noiselimit < 0:
		mysettings["PORTAGE_QUIET"] = "1"

	if mydo == 'depend' and \
		'EAPI' not in mysettings.configdict['pkg']:

		if eapi is not None:
			# From parse-eapi-glep-55 above.
			pass
		elif 'parse-eapi-ebuild-head' in mysettings.features:
			eapi = _parse_eapi_ebuild_head(
				codecs.open(_unicode_encode(ebuild_path,
				encoding=_encodings['fs'], errors='strict'),
				mode='r', encoding=_encodings['content'], errors='replace'))

		if eapi is not None:
			if not eapi_is_supported(eapi):
				raise portage.exception.UnsupportedAPIException(mycpv, eapi)
			mysettings.configdict['pkg']['EAPI'] = eapi

	if mydo != "depend":
		# Metadata vars such as EAPI and RESTRICT are
		# set by the above config.setcpv() call.
		eapi = mysettings["EAPI"]
		if not eapi_is_supported(eapi):
			# can't do anything with this.
			raise portage.exception.UnsupportedAPIException(mycpv, eapi)

	if mysplit[2] == "r0":
		mysettings["PVR"]=mysplit[1]
	else:
		mysettings["PVR"]=mysplit[1]+"-"+mysplit[2]

	if "PATH" in mysettings:
		mysplit=mysettings["PATH"].split(":")
	else:
		mysplit=[]
	# Note: PORTAGE_BIN_PATH may differ from the global constant
	# when portage is reinstalling itself.
	portage_bin_path = mysettings["PORTAGE_BIN_PATH"]
	if portage_bin_path not in mysplit:
		mysettings["PATH"] = portage_bin_path + ":" + mysettings["PATH"]

	# Sandbox needs cannonical paths.
	mysettings["PORTAGE_TMPDIR"] = os.path.realpath(
		mysettings["PORTAGE_TMPDIR"])
	mysettings["BUILD_PREFIX"] = mysettings["PORTAGE_TMPDIR"]+"/portage"
	mysettings["PKG_TMPDIR"]   = mysettings["PORTAGE_TMPDIR"]+"/binpkgs"
	
	# Package {pre,post}inst and {pre,post}rm may overlap, so they must have separate
	# locations in order to prevent interference.
	if mydo in ("unmerge", "prerm", "postrm", "cleanrm"):
		mysettings["PORTAGE_BUILDDIR"] = os.path.join(
			mysettings["PKG_TMPDIR"],
			mysettings["CATEGORY"], mysettings["PF"])
	else:
		mysettings["PORTAGE_BUILDDIR"] = os.path.join(
			mysettings["BUILD_PREFIX"],
			mysettings["CATEGORY"], mysettings["PF"])

	mysettings["HOME"] = os.path.join(mysettings["PORTAGE_BUILDDIR"], "homedir")
	mysettings["WORKDIR"] = os.path.join(mysettings["PORTAGE_BUILDDIR"], "work")
	mysettings["D"] = os.path.join(mysettings["PORTAGE_BUILDDIR"], "image") + os.sep
	mysettings["T"] = os.path.join(mysettings["PORTAGE_BUILDDIR"], "temp")

	mysettings["PORTAGE_BASHRC"] = os.path.join(
		mysettings["PORTAGE_CONFIGROOT"], EBUILD_SH_ENV_FILE)
	mysettings["EBUILD_EXIT_STATUS_FILE"] = os.path.join(
		mysettings["PORTAGE_BUILDDIR"], ".exit_status")

	#set up KV variable -- DEP SPEEDUP :: Don't waste time. Keep var persistent.
	if eapi not in ('0', '1', '2'):
		# Discard KV for EAPIs that don't support it. Cache KV is restored
		# from the backupenv whenever config.reset() is called.
		mysettings.pop('KV', None)
	elif mydo != 'depend' and 'KV' not in mysettings and \
		mydo in ('compile', 'config', 'configure', 'info',
		'install', 'nofetch', 'postinst', 'postrm', 'preinst',
		'prepare', 'prerm', 'setup', 'test', 'unpack'):
		mykv,err1=ExtractKernelVersion(os.path.join(myroot, "usr/src/linux"))
		if mykv:
			# Regular source tree
			mysettings["KV"]=mykv
		else:
			mysettings["KV"]=""
		mysettings.backup_changes("KV")

	# Allow color.map to control colors associated with einfo, ewarn, etc...
	mycolors = []
	for c in ("GOOD", "WARN", "BAD", "HILITE", "BRACKET"):
		mycolors.append("%s=$'%s'" % \
			(c, portage.output.style_to_ansi_code(c)))
	mysettings["PORTAGE_COLORMAP"] = "\n".join(mycolors)

def prepare_build_dirs(myroot, mysettings, cleanup):

	clean_dirs = [mysettings["HOME"]]

	# We enable cleanup when we want to make sure old cruft (such as the old
	# environment) doesn't interfere with the current phase.
	if cleanup:
		clean_dirs.append(mysettings["T"])

	for clean_dir in clean_dirs:
		try:
			shutil.rmtree(clean_dir)
		except OSError as oe:
			if errno.ENOENT == oe.errno:
				pass
			elif errno.EPERM == oe.errno:
				writemsg("%s\n" % oe, noiselevel=-1)
				writemsg(_("Operation Not Permitted: rmtree('%s')\n") % \
					clean_dir, noiselevel=-1)
				return 1
			else:
				raise

	def makedirs(dir_path):
		try:
			os.makedirs(dir_path)
		except OSError as oe:
			if errno.EEXIST == oe.errno:
				pass
			elif errno.EPERM == oe.errno:
				writemsg("%s\n" % oe, noiselevel=-1)
				writemsg(_("Operation Not Permitted: makedirs('%s')\n") % \
					dir_path, noiselevel=-1)
				return False
			else:
				raise
		return True

	mysettings["PKG_LOGDIR"] = os.path.join(mysettings["T"], "logging")

	mydirs = [os.path.dirname(mysettings["PORTAGE_BUILDDIR"])]
	mydirs.append(os.path.dirname(mydirs[-1]))

	try:
		for mydir in mydirs:
			portage.util.ensure_dirs(mydir)
			portage.util.apply_secpass_permissions(mydir,
				gid=portage_gid, uid=portage_uid, mode=0o70, mask=0)
		for dir_key in ("PORTAGE_BUILDDIR", "HOME", "PKG_LOGDIR", "T"):
			"""These directories don't necessarily need to be group writable.
			However, the setup phase is commonly run as a privileged user prior
			to the other phases being run by an unprivileged user.  Currently,
			we use the portage group to ensure that the unprivleged user still
			has write access to these directories in any case."""
			portage.util.ensure_dirs(mysettings[dir_key], mode=0o775)
			portage.util.apply_secpass_permissions(mysettings[dir_key],
				uid=portage_uid, gid=portage_gid)
	except portage.exception.PermissionDenied as e:
		writemsg(_("Permission Denied: %s\n") % str(e), noiselevel=-1)
		return 1
	except portage.exception.OperationNotPermitted as e:
		writemsg(_("Operation Not Permitted: %s\n") % str(e), noiselevel=-1)
		return 1
	except portage.exception.FileNotFound as e:
		writemsg(_("File Not Found: '%s'\n") % str(e), noiselevel=-1)
		return 1

	_prepare_workdir(mysettings)
	if mysettings.get('EBUILD_PHASE') != 'fetch':
		# Avoid spurious permissions adjustments when fetching with
		# a temporary PORTAGE_TMPDIR setting (for fetchonly).
		_prepare_features_dirs(mysettings)

def _adjust_perms_msg(settings, msg):

	def write(msg):
		writemsg(msg, noiselevel=-1)

	background = settings.get("PORTAGE_BACKGROUND") == "1"
	log_path = settings.get("PORTAGE_LOG_FILE")
	log_file = None

	if background and log_path is not None:
		try:
			log_file = codecs.open(_unicode_encode(log_path,
				encoding=_encodings['fs'], errors='strict'),
				mode='a', encoding=_encodings['content'], errors='replace')
		except IOError:
			def write(msg):
				pass
		else:
			def write(msg):
				log_file.write(_unicode_decode(msg))
				log_file.flush()

	try:
		write(msg)
	finally:
		if log_file is not None:
			log_file.close()

def _prepare_features_dirs(mysettings):

	features_dirs = {
		"ccache":{
			"path_dir": "/usr/lib/ccache/bin",
			"basedir_var":"CCACHE_DIR",
			"default_dir":os.path.join(mysettings["PORTAGE_TMPDIR"], "ccache"),
			"always_recurse":False},
		"distcc":{
			"path_dir": "/usr/lib/distcc/bin",
			"basedir_var":"DISTCC_DIR",
			"default_dir":os.path.join(mysettings["BUILD_PREFIX"], ".distcc"),
			"subdirs":("lock", "state"),
			"always_recurse":True}
	}
	dirmode  = 0o2070
	filemode =   0o60
	modemask =    0o2
	restrict = mysettings.get("PORTAGE_RESTRICT","").split()
	from portage.data import secpass
	droppriv = secpass >= 2 and \
		"userpriv" in mysettings.features and \
		"userpriv" not in restrict
	for myfeature, kwargs in features_dirs.items():
		if myfeature in mysettings.features:
			failure = False
			basedir = mysettings.get(kwargs["basedir_var"])
			if basedir is None or not basedir.strip():
				basedir = kwargs["default_dir"]
				mysettings[kwargs["basedir_var"]] = basedir
			try:
				path_dir = kwargs["path_dir"]
				if not os.path.isdir(path_dir):
					raise portage.exception.DirectoryNotFound(path_dir)

				mydirs = [mysettings[kwargs["basedir_var"]]]
				if "subdirs" in kwargs:
					for subdir in kwargs["subdirs"]:
						mydirs.append(os.path.join(basedir, subdir))
				for mydir in mydirs:
					modified = portage.util.ensure_dirs(mydir)
					# Generally, we only want to apply permissions for
					# initial creation.  Otherwise, we don't know exactly what
					# permissions the user wants, so should leave them as-is.
					droppriv_fix = False
					if droppriv:
						st = os.stat(mydir)
						if st.st_gid != portage_gid or \
							not dirmode == (stat.S_IMODE(st.st_mode) & dirmode):
							droppriv_fix = True
						if not droppriv_fix:
							# Check permissions of files in the directory.
							for filename in os.listdir(mydir):
								try:
									subdir_st = os.lstat(
										os.path.join(mydir, filename))
								except OSError:
									continue
								if subdir_st.st_gid != portage_gid or \
									((stat.S_ISDIR(subdir_st.st_mode) and \
									not dirmode == (stat.S_IMODE(subdir_st.st_mode) & dirmode))):
									droppriv_fix = True
									break

					if droppriv_fix:
						_adjust_perms_msg(mysettings,
							colorize("WARN", " * ") + \
							_("Adjusting permissions "
							"for FEATURES=userpriv: '%s'\n") % mydir)
					elif modified:
						_adjust_perms_msg(mysettings,
							colorize("WARN", " * ") + \
							_("Adjusting permissions "
							"for FEATURES=%s: '%s'\n") % (myfeature, mydir))

					if modified or kwargs["always_recurse"] or droppriv_fix:
						def onerror(e):
							raise	# The feature is disabled if a single error
									# occurs during permissions adjustment.
						if not apply_recursive_permissions(mydir,
						gid=portage_gid, dirmode=dirmode, dirmask=modemask,
						filemode=filemode, filemask=modemask, onerror=onerror):
							raise portage.exception.OperationNotPermitted(
								_("Failed to apply recursive permissions for the portage group."))

			except portage.exception.DirectoryNotFound as e:
				failure = True
				writemsg(_("\n!!! Directory does not exist: '%s'\n") % \
					(e,), noiselevel=-1)
				writemsg(_("!!! Disabled FEATURES='%s'\n") % myfeature,
					noiselevel=-1)

			except portage.exception.PortageException as e:
				failure = True
				writemsg("\n!!! %s\n" % str(e), noiselevel=-1)
				writemsg(_("!!! Failed resetting perms on %s='%s'\n") % \
					(kwargs["basedir_var"], basedir), noiselevel=-1)
				writemsg(_("!!! Disabled FEATURES='%s'\n") % myfeature,
					noiselevel=-1)

			if failure:
				mysettings.features.remove(myfeature)
				mysettings['FEATURES'] = ' '.join(sorted(mysettings.features))
				time.sleep(5)

def _prepare_workdir(mysettings):
	workdir_mode = 0o700
	try:
		mode = mysettings["PORTAGE_WORKDIR_MODE"]
		if mode.isdigit():
			parsed_mode = int(mode, 8)
		elif mode == "":
			raise KeyError()
		else:
			raise ValueError()
		if parsed_mode & 0o7777 != parsed_mode:
			raise ValueError("Invalid file mode: %s" % mode)
		else:
			workdir_mode = parsed_mode
	except KeyError as e:
		writemsg(_("!!! PORTAGE_WORKDIR_MODE is unset, using %s.\n") % oct(workdir_mode))
	except ValueError as e:
		if len(str(e)) > 0:
			writemsg("%s\n" % e)
		writemsg(_("!!! Unable to parse PORTAGE_WORKDIR_MODE='%s', using %s.\n") % \
		(mysettings["PORTAGE_WORKDIR_MODE"], oct(workdir_mode)))
	mysettings["PORTAGE_WORKDIR_MODE"] = oct(workdir_mode).replace('o', '')
	try:
		apply_secpass_permissions(mysettings["WORKDIR"],
		uid=portage_uid, gid=portage_gid, mode=workdir_mode)
	except portage.exception.FileNotFound:
		pass # ebuild.sh will create it

	if mysettings.get("PORT_LOGDIR", "") == "":
		while "PORT_LOGDIR" in mysettings:
			del mysettings["PORT_LOGDIR"]
	if "PORT_LOGDIR" in mysettings:
		try:
			modified = portage.util.ensure_dirs(mysettings["PORT_LOGDIR"])
			if modified:
				apply_secpass_permissions(mysettings["PORT_LOGDIR"],
					uid=portage_uid, gid=portage_gid, mode=0o2770)
		except portage.exception.PortageException as e:
			writemsg("!!! %s\n" % str(e), noiselevel=-1)
			writemsg(_("!!! Permission issues with PORT_LOGDIR='%s'\n") % \
				mysettings["PORT_LOGDIR"], noiselevel=-1)
			writemsg(_("!!! Disabling logging.\n"), noiselevel=-1)
			while "PORT_LOGDIR" in mysettings:
				del mysettings["PORT_LOGDIR"]
	if "PORT_LOGDIR" in mysettings and \
		os.access(mysettings["PORT_LOGDIR"], os.W_OK):
		logid_path = os.path.join(mysettings["PORTAGE_BUILDDIR"], ".logid")
		if not os.path.exists(logid_path):
			open(_unicode_encode(logid_path), 'w')
		logid_time = _unicode_decode(time.strftime("%Y%m%d-%H%M%S",
			time.gmtime(os.stat(logid_path).st_mtime)),
			encoding=_encodings['content'], errors='replace')

		if "split-log" in mysettings.features:
			mysettings["PORTAGE_LOG_FILE"] = os.path.join(
				mysettings["PORT_LOGDIR"], "build", "%s/%s:%s.log" % \
				(mysettings["CATEGORY"], mysettings["PF"], logid_time))
		else:
			mysettings["PORTAGE_LOG_FILE"] = os.path.join(
				mysettings["PORT_LOGDIR"], "%s:%s:%s.log" % \
				(mysettings["CATEGORY"], mysettings["PF"], logid_time))

		util.ensure_dirs(os.path.dirname(mysettings["PORTAGE_LOG_FILE"]))

	else:
		# NOTE: When sesandbox is enabled, the local SELinux security policies
		# may not allow output to be piped out of the sesandbox domain. The
		# current policy will allow it to work when a pty is available, but
		# not through a normal pipe. See bug #162404.
		mysettings["PORTAGE_LOG_FILE"] = os.path.join(
			mysettings["T"], "build.log")

def _doebuild_exit_status_check(mydo, settings):
	"""
	Returns an error string if the shell appeared
	to exit unsuccessfully, None otherwise.
	"""
	exit_status_file = settings.get("EBUILD_EXIT_STATUS_FILE")
	if not exit_status_file or \
		os.path.exists(exit_status_file):
		return None
	msg = _("The ebuild phase '%s' has exited "
	"unexpectedly. This type of behavior "
	"is known to be triggered "
	"by things such as failed variable "
	"assignments (bug #190128) or bad substitution "
	"errors (bug #200313). Normally, before exiting, bash should "
	"have displayed an error message above. If bash did not "
	"produce an error message above, it's possible "
	"that the ebuild has called `exit` when it "
	"should have called `die` instead. This behavior may also "
	"be triggered by a corrupt bash binary or a hardware "
	"problem such as memory or cpu malfunction. If the problem is not "
	"reproducible or it appears to occur randomly, then it is likely "
	"to be triggered by a hardware problem. "
	"If you suspect a hardware problem then you should "
	"try some basic hardware diagnostics such as memtest. "
	"Please do not report this as a bug unless it is consistently "
	"reproducible and you are sure that your bash binary and hardware "
	"are functioning properly.") % mydo
	return msg

def _doebuild_exit_status_check_and_log(settings, mydo, retval):
	msg = _doebuild_exit_status_check(mydo, settings)
	if msg:
		if retval == os.EX_OK:
			retval = 1
		from textwrap import wrap
		from portage.elog.messages import eerror
		for l in wrap(msg, 72):
			eerror(l, phase=mydo, key=settings.mycpv)
	return retval

def _doebuild_exit_status_unlink(exit_status_file):
	"""
	Double check to make sure it really doesn't exist
	and raise an OSError if it still does (it shouldn't).
	OSError if necessary.
	"""
	if not exit_status_file:
		return
	try:
		os.unlink(exit_status_file)
	except OSError:
		pass
	if os.path.exists(exit_status_file):
		os.unlink(exit_status_file)

_doebuild_manifest_exempt_depend = 0
_doebuild_manifest_cache = None
_doebuild_broken_ebuilds = set()
_doebuild_broken_manifests = set()

def doebuild(myebuild, mydo, myroot, mysettings, debug=0, listonly=0,
	fetchonly=0, cleanup=0, dbkey=None, use_cache=1, fetchall=0, tree=None,
	mydbapi=None, vartree=None, prev_mtimes=None,
	fd_pipes=None, returnpid=False):

	"""
	Wrapper function that invokes specific ebuild phases through the spawning
	of ebuild.sh
	
	@param myebuild: name of the ebuild to invoke the phase on (CPV)
	@type myebuild: String
	@param mydo: Phase to run
	@type mydo: String
	@param myroot: $ROOT (usually '/', see man make.conf)
	@type myroot: String
	@param mysettings: Portage Configuration
	@type mysettings: instance of portage.config
	@param debug: Turns on various debug information (eg, debug for spawn)
	@type debug: Boolean
	@param listonly: Used to wrap fetch(); passed such that fetch only lists files required.
	@type listonly: Boolean
	@param fetchonly: Used to wrap fetch(); passed such that files are only fetched (no other actions)
	@type fetchonly: Boolean
	@param cleanup: Passed to prepare_build_dirs (TODO: what does it do?)
	@type cleanup: Boolean
	@param dbkey: A dict (usually keys and values from the depend phase, such as KEYWORDS, USE, etc..)
	@type dbkey: Dict or String
	@param use_cache: Enables the cache
	@type use_cache: Boolean
	@param fetchall: Used to wrap fetch(), fetches all URIs (even ones invalid due to USE conditionals)
	@type fetchall: Boolean
	@param tree: Which tree to use ('vartree','porttree','bintree', etc..), defaults to 'porttree'
	@type tree: String
	@param mydbapi: a dbapi instance to pass to various functions; this should be a portdbapi instance.
	@type mydbapi: portdbapi instance
	@param vartree: A instance of vartree; used for aux_get calls, defaults to db[myroot]['vartree']
	@type vartree: vartree instance
	@param prev_mtimes: A dict of { filename:mtime } keys used by merge() to do config_protection
	@type prev_mtimes: dictionary
	@param fd_pipes: A dict of mapping for pipes, { '0': stdin, '1': stdout }
		for example.
	@type fd_pipes: Dictionary
	@param returnpid: Return a list of process IDs for a successful spawn, or
		an integer value if spawn is unsuccessful. NOTE: This requires the
		caller clean up all returned PIDs.
	@type returnpid: Boolean
	@rtype: Boolean
	@returns:
	1. 0 for success
	2. 1 for error
	
	Most errors have an accompanying error message.
	
	listonly and fetchonly are only really necessary for operations involving 'fetch'
	prev_mtimes are only necessary for merge operations.
	Other variables may not be strictly required, many have defaults that are set inside of doebuild.
	
	"""
	
	if not tree:
		writemsg("Warning: tree not specified to doebuild\n")
		tree = "porttree"
	global db
	
	# chunked out deps for each phase, so that ebuild binary can use it 
	# to collapse targets down.
	actionmap_deps={
	"setup":  [],
	"unpack": ["setup"],
	"prepare": ["unpack"],
	"configure": ["prepare"],
	"compile":["configure"],
	"test":   ["compile"],
	"install":["test"],
	"rpm":    ["install"],
	"package":["install"],
	}
	
	if mydbapi is None:
		mydbapi = db[myroot][tree].dbapi

	if vartree is None and mydo in ("merge", "qmerge", "unmerge"):
		vartree = db[myroot]["vartree"]

	features = mysettings.features
	noauto = "noauto" in features
	from portage.data import secpass

	clean_phases = ("clean", "cleanrm")
	validcommands = ["help","clean","prerm","postrm","cleanrm","preinst","postinst",
	                "config", "info", "setup", "depend", "pretend",
	                "fetch", "fetchall", "digest",
	                "unpack", "prepare", "configure", "compile", "test",
	                "install", "rpm", "qmerge", "merge",
	                "package","unmerge", "manifest"]

	if mydo not in validcommands:
		validcommands.sort()
		writemsg("!!! doebuild: '%s' is not one of the following valid commands:" % mydo,
			noiselevel=-1)
		for vcount in range(len(validcommands)):
			if vcount%6 == 0:
				writemsg("\n!!! ", noiselevel=-1)
			writemsg(validcommands[vcount].ljust(11), noiselevel=-1)
		writemsg("\n", noiselevel=-1)
		return 1

	if mydo == "fetchall":
		fetchall = 1
		mydo = "fetch"

	parallel_fetchonly = mydo in ("fetch", "fetchall") and \
		"PORTAGE_PARALLEL_FETCHONLY" in mysettings

	if mydo not in clean_phases and not os.path.exists(myebuild):
		writemsg("!!! doebuild: %s not found for %s\n" % (myebuild, mydo),
			noiselevel=-1)
		return 1

	global _doebuild_manifest_exempt_depend

	if "strict" in features and \
		"digest" not in features and \
		tree == "porttree" and \
		mydo not in ("digest", "manifest", "help") and \
		not _doebuild_manifest_exempt_depend:
		# Always verify the ebuild checksums before executing it.
		global _doebuild_manifest_cache, _doebuild_broken_ebuilds, \
			_doebuild_broken_ebuilds

		if myebuild in _doebuild_broken_ebuilds:
			return 1

		pkgdir = os.path.dirname(myebuild)
		manifest_path = os.path.join(pkgdir, "Manifest")

		# Avoid checking the same Manifest several times in a row during a
		# regen with an empty cache.
		if _doebuild_manifest_cache is None or \
			_doebuild_manifest_cache.getFullname() != manifest_path:
			_doebuild_manifest_cache = None
			if not os.path.exists(manifest_path):
				out = portage.output.EOutput()
				out.eerror(_("Manifest not found for '%s'") % (myebuild,))
				_doebuild_broken_ebuilds.add(myebuild)
				return 1
			mf = Manifest(pkgdir, mysettings["DISTDIR"])

		else:
			mf = _doebuild_manifest_cache

		try:
			mf.checkFileHashes("EBUILD", os.path.basename(myebuild))
		except KeyError:
			out = portage.output.EOutput()
			out.eerror(_("Missing digest for '%s'") % (myebuild,))
			_doebuild_broken_ebuilds.add(myebuild)
			return 1
		except portage.exception.FileNotFound:
			out = portage.output.EOutput()
			out.eerror(_("A file listed in the Manifest "
				"could not be found: '%s'") % (myebuild,))
			_doebuild_broken_ebuilds.add(myebuild)
			return 1
		except portage.exception.DigestException as e:
			out = portage.output.EOutput()
			out.eerror(_("Digest verification failed:"))
			out.eerror("%s" % e.value[0])
			out.eerror(_("Reason: %s") % e.value[1])
			out.eerror(_("Got: %s") % e.value[2])
			out.eerror(_("Expected: %s") % e.value[3])
			_doebuild_broken_ebuilds.add(myebuild)
			return 1

		if mf.getFullname() in _doebuild_broken_manifests:
			return 1

		if mf is not _doebuild_manifest_cache:

			# Make sure that all of the ebuilds are
			# actually listed in the Manifest.
			glep55 = 'parse-eapi-glep-55' in mysettings.features
			for f in os.listdir(pkgdir):
				pf = None
				if glep55:
					pf, eapi = _split_ebuild_name_glep55(f)
				elif f[-7:] == '.ebuild':
					pf = f[:-7]
				if pf is not None and not mf.hasFile("EBUILD", f):
					f = os.path.join(pkgdir, f)
					if f not in _doebuild_broken_ebuilds:
						out = portage.output.EOutput()
						out.eerror(_("A file is not listed in the "
							"Manifest: '%s'") % (f,))
					_doebuild_broken_manifests.add(manifest_path)
					return 1

			# Only cache it if the above stray files test succeeds.
			_doebuild_manifest_cache = mf

	def exit_status_check(retval):
		msg = _doebuild_exit_status_check(mydo, mysettings)
		if msg:
			if retval == os.EX_OK:
				retval = 1
			from textwrap import wrap
			from portage.elog.messages import eerror
			for l in wrap(msg, 72):
				eerror(l, phase=mydo, key=mysettings.mycpv)
		return retval

	# Note: PORTAGE_BIN_PATH may differ from the global
	# constant when portage is reinstalling itself.
	portage_bin_path = mysettings["PORTAGE_BIN_PATH"]
	ebuild_sh_binary = os.path.join(portage_bin_path,
		os.path.basename(EBUILD_SH_BINARY))
	misc_sh_binary = os.path.join(portage_bin_path,
		os.path.basename(MISC_SH_BINARY))

	logfile=None
	builddir_lock = None
	tmpdir = None
	tmpdir_orig = None

	try:
		if mydo in ("digest", "manifest", "help"):
			# Temporarily exempt the depend phase from manifest checks, in case
			# aux_get calls trigger cache generation.
			_doebuild_manifest_exempt_depend += 1

		# If we don't need much space and we don't need a constant location,
		# we can temporarily override PORTAGE_TMPDIR with a random temp dir
		# so that there's no need for locking and it can be used even if the
		# user isn't in the portage group.
		if mydo in ("info",):
			from tempfile import mkdtemp
			tmpdir = mkdtemp()
			tmpdir_orig = mysettings["PORTAGE_TMPDIR"]
			mysettings["PORTAGE_TMPDIR"] = tmpdir

		doebuild_environment(myebuild, mydo, myroot, mysettings, debug,
			use_cache, mydbapi)

		if mydo in clean_phases:
			retval = spawn(_shell_quote(ebuild_sh_binary) + " clean",
				mysettings, debug=debug, fd_pipes=fd_pipes, free=1,
				logfile=None, returnpid=returnpid)
			return retval

		restrict = set(mysettings.get('PORTAGE_RESTRICT', '').split())
		# get possible slot information from the deps file
		if mydo == "depend":
			writemsg("!!! DEBUG: dbkey: %s\n" % str(dbkey), 2)
			droppriv = "userpriv" in mysettings.features
			if returnpid:
				mypids = spawn(_shell_quote(ebuild_sh_binary) + " depend",
					mysettings, fd_pipes=fd_pipes, returnpid=True,
					droppriv=droppriv)
				return mypids
			elif isinstance(dbkey, dict):
				mysettings["dbkey"] = ""
				pr, pw = os.pipe()
				fd_pipes = {
					0:sys.stdin.fileno(),
					1:sys.stdout.fileno(),
					2:sys.stderr.fileno(),
					9:pw}
				mypids = spawn(_shell_quote(ebuild_sh_binary) + " depend",
					mysettings,
					fd_pipes=fd_pipes, returnpid=True, droppriv=droppriv)
				os.close(pw) # belongs exclusively to the child process now
				f = os.fdopen(pr, 'rb')
				for k, v in zip(auxdbkeys,
					(_unicode_decode(line).rstrip('\n') for line in f)):
					dbkey[k] = v
				f.close()
				retval = os.waitpid(mypids[0], 0)[1]
				portage.process.spawned_pids.remove(mypids[0])
				# If it got a signal, return the signal that was sent, but
				# shift in order to distinguish it from a return value. (just
				# like portage.process.spawn() would do).
				if retval & 0xff:
					retval = (retval & 0xff) << 8
				else:
					# Otherwise, return its exit code.
					retval = retval >> 8
				if retval == os.EX_OK and len(dbkey) != len(auxdbkeys):
					# Don't trust bash's returncode if the
					# number of lines is incorrect.
					retval = 1
				return retval
			elif dbkey:
				mysettings["dbkey"] = dbkey
			else:
				mysettings["dbkey"] = \
					os.path.join(mysettings.depcachedir, "aux_db_key_temp")

			return spawn(_shell_quote(ebuild_sh_binary) + " depend",
				mysettings,
				droppriv=droppriv)

		# Validate dependency metadata here to ensure that ebuilds with invalid
		# data are never installed via the ebuild command. Don't bother when
		# returnpid == True since there's no need to do this every time emerge
		# executes a phase.
		if not returnpid:
			rval = _validate_deps(mysettings, myroot, mydo, mydbapi)
			if rval != os.EX_OK:
				return rval

		if "PORTAGE_TMPDIR" not in mysettings or \
			not os.path.isdir(mysettings["PORTAGE_TMPDIR"]):
			writemsg(_("The directory specified in your "
				"PORTAGE_TMPDIR variable, '%s',\n"
				"does not exist.  Please create this directory or "
				"correct your PORTAGE_TMPDIR setting.\n") % mysettings.get("PORTAGE_TMPDIR", ""), noiselevel=-1)
			return 1
		
		# as some people use a separate PORTAGE_TMPDIR mount
		# we prefer that as the checks below would otherwise be pointless
		# for those people.
		if os.path.exists(os.path.join(mysettings["PORTAGE_TMPDIR"], "portage")):
			checkdir = os.path.join(mysettings["PORTAGE_TMPDIR"], "portage")
		else:
			checkdir = mysettings["PORTAGE_TMPDIR"]

		if not os.access(checkdir, os.W_OK):
			writemsg(_("%s is not writable.\n"
				"Likely cause is that you've mounted it as readonly.\n") % checkdir,
				noiselevel=-1)
			return 1
		else:
			from tempfile import NamedTemporaryFile
			fd = NamedTemporaryFile(prefix="exectest-", dir=checkdir)
			os.chmod(fd.name, 0o755)
			if not os.access(fd.name, os.X_OK):
				writemsg(_("Can not execute files in %s\n"
					"Likely cause is that you've mounted it with one of the\n"
					"following mount options: 'noexec', 'user', 'users'\n\n"
					"Please make sure that portage can execute files in this directory.\n") % checkdir,
					noiselevel=-1)
				fd.close()
				return 1
			fd.close()
		del checkdir

		if mydo == "unmerge":
			return unmerge(mysettings["CATEGORY"],
				mysettings["PF"], myroot, mysettings, vartree=vartree)

		# Build directory creation isn't required for any of these.
		# In the fetch phase, the directory is needed only for RESTRICT=fetch
		# in order to satisfy the sane $PWD requirement (from bug #239560)
		# when pkg_nofetch is spawned.
		have_build_dirs = False
		if not parallel_fetchonly and \
			mydo not in ('digest', 'help', 'manifest') and \
			not (mydo == 'fetch' and 'fetch' not in restrict):
			mystatus = prepare_build_dirs(myroot, mysettings, cleanup)
			if mystatus:
				return mystatus
			have_build_dirs = True

			# emerge handles logging externally
			if not returnpid:
				# PORTAGE_LOG_FILE is set by the
				# above prepare_build_dirs() call.
				logfile = mysettings.get("PORTAGE_LOG_FILE")

		if have_build_dirs:
			env_file = os.path.join(mysettings["T"], "environment")
			env_stat = None
			saved_env = None
			try:
				env_stat = os.stat(env_file)
			except OSError as e:
				if e.errno != errno.ENOENT:
					raise
				del e
			if not env_stat:
				saved_env = os.path.join(
					os.path.dirname(myebuild), "environment.bz2")
				if not os.path.isfile(saved_env):
					saved_env = None
			if saved_env:
				retval = os.system(
					"bzip2 -dc %s > %s" % \
					(_shell_quote(saved_env),
					_shell_quote(env_file)))
				try:
					env_stat = os.stat(env_file)
				except OSError as e:
					if e.errno != errno.ENOENT:
						raise
					del e
				if os.WIFEXITED(retval) and \
					os.WEXITSTATUS(retval) == os.EX_OK and \
					env_stat and env_stat.st_size > 0:
					# This is a signal to ebuild.sh, so that it knows to filter
					# out things like SANDBOX_{DENY,PREDICT,READ,WRITE} that
					# would be preserved between normal phases.
					open(_unicode_encode(env_file + '.raw'), 'w')
				else:
					writemsg(_("!!! Error extracting saved "
						"environment: '%s'\n") % \
						saved_env, noiselevel=-1)
					try:
						os.unlink(env_file)
					except OSError as e:
						if e.errno != errno.ENOENT:
							raise
						del e
					env_stat = None
			if env_stat:
				pass
			else:
				for var in ("ARCH", ):
					value = mysettings.get(var)
					if value and value.strip():
						continue
					msg = _("%(var)s is not set... "
						"Are you missing the '%(configroot)setc/make.profile' symlink? "
						"Is the symlink correct? "
						"Is your portage tree complete?") % \
						{"var": var, "configroot": mysettings["PORTAGE_CONFIGROOT"]}
					from portage.elog.messages import eerror
					from textwrap import wrap
					for line in wrap(msg, 70):
						eerror(line, phase="setup", key=mysettings.mycpv)
					from portage.elog import elog_process
					elog_process(mysettings.mycpv, mysettings)
					return 1
			del env_file, env_stat, saved_env
			_doebuild_exit_status_unlink(
				mysettings.get("EBUILD_EXIT_STATUS_FILE"))
		else:
			mysettings.pop("EBUILD_EXIT_STATUS_FILE", None)

		# if any of these are being called, handle them -- running them out of
		# the sandbox -- and stop now.
		if mydo == "help":
			return spawn(_shell_quote(ebuild_sh_binary) + " " + mydo,
				mysettings, debug=debug, free=1, logfile=logfile)
		elif mydo == "setup":
			retval = spawn(
				_shell_quote(ebuild_sh_binary) + " " + mydo, mysettings,
				debug=debug, free=1, logfile=logfile, fd_pipes=fd_pipes,
				returnpid=returnpid)
			if returnpid:
				return retval
			retval = exit_status_check(retval)
			if secpass >= 2:
				""" Privileged phases may have left files that need to be made
				writable to a less privileged user."""
				apply_recursive_permissions(mysettings["T"],
					uid=portage_uid, gid=portage_gid, dirmode=0o70, dirmask=0,
					filemode=0o60, filemask=0)
			return retval
		elif mydo == "preinst":
			phase_retval = spawn(
				_shell_quote(ebuild_sh_binary) + " " + mydo,
				mysettings, debug=debug, free=1, logfile=logfile,
				fd_pipes=fd_pipes, returnpid=returnpid)

			if returnpid:
				return phase_retval

			phase_retval = exit_status_check(phase_retval)
			if phase_retval == os.EX_OK:
				_doebuild_exit_status_unlink(
					mysettings.get("EBUILD_EXIT_STATUS_FILE"))
				mysettings.pop("EBUILD_PHASE", None)
				phase_retval = spawn(
					" ".join(_post_pkg_preinst_cmd(mysettings)),
					mysettings, debug=debug, free=1, logfile=logfile)
				phase_retval = exit_status_check(phase_retval)
				if phase_retval != os.EX_OK:
					writemsg(_("!!! post preinst failed; exiting.\n"),
						noiselevel=-1)
			return phase_retval
		elif mydo == "postinst":
			phase_retval = spawn(
				_shell_quote(ebuild_sh_binary) + " " + mydo,
				mysettings, debug=debug, free=1, logfile=logfile,
				fd_pipes=fd_pipes, returnpid=returnpid)

			if returnpid:
				return phase_retval

			phase_retval = exit_status_check(phase_retval)
			if phase_retval == os.EX_OK:
				_doebuild_exit_status_unlink(
					mysettings.get("EBUILD_EXIT_STATUS_FILE"))
				mysettings.pop("EBUILD_PHASE", None)
				phase_retval = spawn(" ".join(_post_pkg_postinst_cmd(mysettings)),
					mysettings, debug=debug, free=1, logfile=logfile)
				phase_retval = exit_status_check(phase_retval)
				if phase_retval != os.EX_OK:
					writemsg(_("!!! post postinst failed; exiting.\n"),
						noiselevel=-1)
			return phase_retval
		elif mydo in ("prerm", "postrm", "config", "info"):
			retval =  spawn(
				_shell_quote(ebuild_sh_binary) + " " + mydo,
				mysettings, debug=debug, free=1, logfile=logfile,
				fd_pipes=fd_pipes, returnpid=returnpid)

			if returnpid:
				return retval

			retval = exit_status_check(retval)
			return retval

		mycpv = "/".join((mysettings["CATEGORY"], mysettings["PF"]))

		emerge_skip_distfiles = returnpid
		emerge_skip_digest = returnpid
		# Only try and fetch the files if we are going to need them ...
		# otherwise, if user has FEATURES=noauto and they run `ebuild clean
		# unpack compile install`, we will try and fetch 4 times :/
		need_distfiles = not emerge_skip_distfiles and \
			(mydo in ("fetch", "unpack") or \
			mydo not in ("digest", "manifest") and "noauto" not in features)
		alist = mysettings.configdict["pkg"].get("A")
		aalist = mysettings.configdict["pkg"].get("AA")
		if need_distfiles or alist is None or aalist is None:
			# Make sure we get the correct tree in case there are overlays.
			mytree = os.path.realpath(
				os.path.dirname(os.path.dirname(mysettings["O"])))
			useflags = mysettings["PORTAGE_USE"].split()
			try:
				alist = mydbapi.getFetchMap(mycpv, useflags=useflags,
					mytree=mytree)
				aalist = mydbapi.getFetchMap(mycpv, mytree=mytree)
			except portage.exception.InvalidDependString as e:
				writemsg("!!! %s\n" % str(e), noiselevel=-1)
				writemsg(_("!!! Invalid SRC_URI for '%s'.\n") % mycpv,
					noiselevel=-1)
				del e
				return 1
			mysettings.configdict["pkg"]["A"] = " ".join(alist)
			mysettings.configdict["pkg"]["AA"] = " ".join(aalist)
		else:
			alist = set(alist.split())
			aalist = set(aalist.split())
		if ("mirror" in features) or fetchall:
			fetchme = aalist
			checkme = aalist
		else:
			fetchme = alist
			checkme = alist

		if mydo == "fetch":
			# Files are already checked inside fetch(),
			# so do not check them again.
			checkme = []

		if not emerge_skip_distfiles and \
			need_distfiles and not fetch(
			fetchme, mysettings, listonly=listonly, fetchonly=fetchonly):
			return 1

		if mydo == "fetch" and listonly:
			return 0

		try:
			if mydo == "manifest":
				return not digestgen(aalist, mysettings, overwrite=1,
					manifestonly=1, myportdb=mydbapi)
			elif mydo == "digest":
				return not digestgen(aalist, mysettings, overwrite=1,
					myportdb=mydbapi)
			elif mydo != 'fetch' and not emerge_skip_digest and \
				"digest" in mysettings.features:
				# Don't do this when called by emerge or when called just
				# for fetch (especially parallel-fetch) since it's not needed
				# and it can interfere with parallel tasks.
				digestgen(aalist, mysettings, overwrite=0, myportdb=mydbapi)
		except portage.exception.PermissionDenied as e:
			writemsg(_("!!! Permission Denied: %s\n") % (e,), noiselevel=-1)
			if mydo in ("digest", "manifest"):
				return 1

		# See above comment about fetching only when needed
		if not emerge_skip_distfiles and \
			not digestcheck(checkme, mysettings, "strict" in features):
			return 1

		if mydo == "fetch":
			return 0

		# remove PORTAGE_ACTUAL_DISTDIR once cvs/svn is supported via SRC_URI
		if (mydo != "setup" and "noauto" not in features) or mydo == "unpack":
			orig_distdir = mysettings["DISTDIR"]
			mysettings["PORTAGE_ACTUAL_DISTDIR"] = orig_distdir
			edpath = mysettings["DISTDIR"] = \
				os.path.join(mysettings["PORTAGE_BUILDDIR"], "distdir")
			portage.util.ensure_dirs(edpath, gid=portage_gid, mode=0o755)

			# Remove any unexpected files or directories.
			for x in os.listdir(edpath):
				symlink_path = os.path.join(edpath, x)
				st = os.lstat(symlink_path)
				if x in alist and stat.S_ISLNK(st.st_mode):
					continue
				if stat.S_ISDIR(st.st_mode):
					shutil.rmtree(symlink_path)
				else:
					os.unlink(symlink_path)

			# Check for existing symlinks and recreate if necessary.
			for x in alist:
				symlink_path = os.path.join(edpath, x)
				target = os.path.join(orig_distdir, x)
				try:
					link_target = os.readlink(symlink_path)
				except OSError:
					os.symlink(target, symlink_path)
				else:
					if link_target != target:
						os.unlink(symlink_path)
						os.symlink(target, symlink_path)

		#initial dep checks complete; time to process main commands

		restrict = mysettings["PORTAGE_RESTRICT"].split()
		nosandbox = (("userpriv" in features) and \
			("usersandbox" not in features) and \
			"userpriv" not in restrict and \
			"nouserpriv" not in restrict)
		if nosandbox and ("userpriv" not in features or \
			"userpriv" in restrict or \
			"nouserpriv" in restrict):
			nosandbox = ("sandbox" not in features and \
				"usersandbox" not in features)

		sesandbox = mysettings.selinux_enabled() and \
			"sesandbox" in mysettings.features

		droppriv = "userpriv" in mysettings.features and \
			"userpriv" not in restrict and \
			secpass >= 2

		fakeroot = "fakeroot" in mysettings.features

		ebuild_sh = _shell_quote(ebuild_sh_binary) + " %s"
		misc_sh = _shell_quote(misc_sh_binary) + " dyn_%s"

		# args are for the to spawn function
		actionmap = {
"pretend":  {"cmd":ebuild_sh, "args":{"droppriv":0,        "free":1,         "sesandbox":0,         "fakeroot":0}},
"setup":    {"cmd":ebuild_sh, "args":{"droppriv":0,        "free":1,         "sesandbox":0,         "fakeroot":0}},
"unpack":   {"cmd":ebuild_sh, "args":{"droppriv":droppriv, "free":0,         "sesandbox":sesandbox, "fakeroot":0}},
"prepare":  {"cmd":ebuild_sh, "args":{"droppriv":droppriv, "free":0,         "sesandbox":sesandbox, "fakeroot":0}},
"configure":{"cmd":ebuild_sh, "args":{"droppriv":droppriv, "free":nosandbox, "sesandbox":sesandbox, "fakeroot":0}},
"compile":  {"cmd":ebuild_sh, "args":{"droppriv":droppriv, "free":nosandbox, "sesandbox":sesandbox, "fakeroot":0}},
"test":     {"cmd":ebuild_sh, "args":{"droppriv":droppriv, "free":nosandbox, "sesandbox":sesandbox, "fakeroot":0}},
"install":  {"cmd":ebuild_sh, "args":{"droppriv":0,        "free":0,         "sesandbox":sesandbox, "fakeroot":fakeroot}},
"rpm":      {"cmd":misc_sh,   "args":{"droppriv":0,        "free":0,         "sesandbox":0,         "fakeroot":fakeroot}},
"package":  {"cmd":misc_sh,   "args":{"droppriv":0,        "free":0,         "sesandbox":0,         "fakeroot":fakeroot}},
		}

		# merge the deps in so we have again a 'full' actionmap
		# be glad when this can die.
		for x in actionmap:
			if len(actionmap_deps.get(x, [])):
				actionmap[x]["dep"] = ' '.join(actionmap_deps[x])

		if mydo in actionmap:
			if mydo == "package":
				# Make sure the package directory exists before executing
				# this phase. This can raise PermissionDenied if
				# the current user doesn't have write access to $PKGDIR.
				parent_dir = os.path.join(mysettings["PKGDIR"],
					mysettings["CATEGORY"])
				portage.util.ensure_dirs(parent_dir)
				if not os.access(parent_dir, os.W_OK):
					raise portage.exception.PermissionDenied(
						"access('%s', os.W_OK)" % parent_dir)
			retval = spawnebuild(mydo,
				actionmap, mysettings, debug, logfile=logfile,
				fd_pipes=fd_pipes, returnpid=returnpid)
		elif mydo=="qmerge":
			# check to ensure install was run.  this *only* pops up when users
			# forget it and are using ebuild
			if not os.path.exists(
				os.path.join(mysettings["PORTAGE_BUILDDIR"], ".installed")):
				writemsg(_("!!! mydo=qmerge, but the install phase has not been run\n"),
					noiselevel=-1)
				return 1
			# qmerge is a special phase that implies noclean.
			if "noclean" not in mysettings.features:
				mysettings.features.add("noclean")
			#qmerge is specifically not supposed to do a runtime dep check
			retval = merge(
				mysettings["CATEGORY"], mysettings["PF"], mysettings["D"],
				os.path.join(mysettings["PORTAGE_BUILDDIR"], "build-info"),
				myroot, mysettings, myebuild=mysettings["EBUILD"], mytree=tree,
				mydbapi=mydbapi, vartree=vartree, prev_mtimes=prev_mtimes)
		elif mydo=="merge":
			retval = spawnebuild("install", actionmap, mysettings, debug,
				alwaysdep=1, logfile=logfile, fd_pipes=fd_pipes,
				returnpid=returnpid)
			retval = exit_status_check(retval)
			if retval != os.EX_OK:
				# The merge phase handles this already.  Callers don't know how
				# far this function got, so we have to call elog_process() here
				# so that it's only called once.
				from portage.elog import elog_process
				elog_process(mysettings.mycpv, mysettings)
			if retval == os.EX_OK:
				retval = merge(mysettings["CATEGORY"], mysettings["PF"],
					mysettings["D"], os.path.join(mysettings["PORTAGE_BUILDDIR"],
					"build-info"), myroot, mysettings,
					myebuild=mysettings["EBUILD"], mytree=tree, mydbapi=mydbapi,
					vartree=vartree, prev_mtimes=prev_mtimes)
		else:
			print(_("!!! Unknown mydo: %s") % mydo)
			return 1

		return retval

	finally:

		if tmpdir:
			mysettings["PORTAGE_TMPDIR"] = tmpdir_orig
			shutil.rmtree(tmpdir)
		if builddir_lock:
			portage.locks.unlockdir(builddir_lock)

		# Make sure that DISTDIR is restored to it's normal value before we return!
		if "PORTAGE_ACTUAL_DISTDIR" in mysettings:
			mysettings["DISTDIR"] = mysettings["PORTAGE_ACTUAL_DISTDIR"]
			del mysettings["PORTAGE_ACTUAL_DISTDIR"]

		if logfile:
			try:
				if os.stat(logfile).st_size == 0:
					os.unlink(logfile)
			except OSError:
				pass

		if mydo in ("digest", "manifest", "help"):
			# If necessary, depend phase has been triggered by aux_get calls
			# and the exemption is no longer needed.
			_doebuild_manifest_exempt_depend -= 1

def _validate_deps(mysettings, myroot, mydo, mydbapi):

	invalid_dep_exempt_phases = \
		set(["clean", "cleanrm", "help", "prerm", "postrm"])
	dep_keys = ["DEPEND", "RDEPEND", "PDEPEND"]
	misc_keys = ["LICENSE", "PROPERTIES", "PROVIDE", "RESTRICT", "SRC_URI"]
	other_keys = ["SLOT"]
	all_keys = dep_keys + misc_keys + other_keys
	metadata = dict(zip(all_keys,
		mydbapi.aux_get(mysettings.mycpv, all_keys)))

	class FakeTree(object):
		def __init__(self, mydb):
			self.dbapi = mydb
	dep_check_trees = {myroot:{}}
	dep_check_trees[myroot]["porttree"] = \
		FakeTree(fakedbapi(settings=mysettings))

	msgs = []
	for dep_type in dep_keys:
		mycheck = dep_check(metadata[dep_type], None, mysettings,
			myuse="all", myroot=myroot, trees=dep_check_trees)
		if not mycheck[0]:
			msgs.append("  %s: %s\n    %s\n" % (
				dep_type, metadata[dep_type], mycheck[1]))

	for k in misc_keys:
		try:
			portage.dep.use_reduce(
				portage.dep.paren_reduce(metadata[k]), matchall=True)
		except portage.exception.InvalidDependString as e:
			msgs.append("  %s: %s\n    %s\n" % (
				k, metadata[k], str(e)))

	if not metadata["SLOT"]:
		msgs.append(_("  SLOT is undefined\n"))

	if msgs:
		portage.util.writemsg_level(_("Error(s) in metadata for '%s':\n") % \
			(mysettings.mycpv,), level=logging.ERROR, noiselevel=-1)
		for x in msgs:
			portage.util.writemsg_level(x,
				level=logging.ERROR, noiselevel=-1)
		if mydo not in invalid_dep_exempt_phases:
			return 1

	return os.EX_OK

expandcache={}

def _movefile(src, dest, **kwargs):
	"""Calls movefile and raises a PortageException if an error occurs."""
	if movefile(src, dest, **kwargs) is None:
		raise portage.exception.PortageException(
			"mv '%s' '%s'" % (src, dest))

def movefile(src, dest, newmtime=None, sstat=None, mysettings=None,
		hardlink_candidates=None, encoding=_encodings['fs']):
	"""moves a file from src to dest, preserving all permissions and attributes; mtime will
	be preserved even when moving across filesystems.  Returns true on success and false on
	failure.  Move is atomic."""
	#print "movefile("+str(src)+","+str(dest)+","+str(newmtime)+","+str(sstat)+")"

	if mysettings is None:
		global settings
		mysettings = settings

	selinux_enabled = mysettings.selinux_enabled()
	if selinux_enabled:
		selinux = _unicode_module_wrapper(_selinux, encoding=encoding)

	lchown = _unicode_func_wrapper(data.lchown, encoding=encoding)
	os = _unicode_module_wrapper(_os,
		encoding=encoding, overrides=_os_overrides)
	shutil = _unicode_module_wrapper(_shutil, encoding=encoding)

	try:
		if not sstat:
			sstat=os.lstat(src)

	except SystemExit as e:
		raise
	except Exception as e:
		print(_("!!! Stating source file failed... movefile()"))
		print("!!!",e)
		return None

	destexists=1
	try:
		dstat=os.lstat(dest)
	except (OSError, IOError):
		dstat=os.lstat(os.path.dirname(dest))
		destexists=0

	if bsd_chflags:
		if destexists and dstat.st_flags != 0:
			bsd_chflags.lchflags(dest, 0)
		# Use normal stat/chflags for the parent since we want to
		# follow any symlinks to the real parent directory.
		pflags = os.stat(os.path.dirname(dest)).st_flags
		if pflags != 0:
			bsd_chflags.chflags(os.path.dirname(dest), 0)

	if destexists:
		if stat.S_ISLNK(dstat[stat.ST_MODE]):
			try:
				os.unlink(dest)
				destexists=0
			except SystemExit as e:
				raise
			except Exception as e:
				pass

	if stat.S_ISLNK(sstat[stat.ST_MODE]):
		try:
			target=os.readlink(src)
			if mysettings and mysettings["D"]:
				if target.find(mysettings["D"])==0:
					target=target[len(mysettings["D"]):]
			if destexists and not stat.S_ISDIR(dstat[stat.ST_MODE]):
				os.unlink(dest)
			if selinux_enabled:
				selinux.symlink(target, dest, src)
			else:
				os.symlink(target,dest)
			lchown(dest,sstat[stat.ST_UID],sstat[stat.ST_GID])
			# utime() only works on the target of a symlink, so it's not
			# possible to perserve mtime on symlinks.
			return os.lstat(dest)[stat.ST_MTIME]
		except SystemExit as e:
			raise
		except Exception as e:
			print(_("!!! failed to properly create symlink:"))
			print("!!!",dest,"->",target)
			print("!!!",e)
			return None

	hardlinked = False
	# Since identical files might be merged to multiple filesystems,
	# so os.link() calls might fail for some paths, so try them all.
	# For atomic replacement, first create the link as a temp file
	# and them use os.rename() to replace the destination.
	if hardlink_candidates:
		head, tail = os.path.split(dest)
		hardlink_tmp = os.path.join(head, ".%s._portage_merge_.%s" % \
			(tail, os.getpid()))
		try:
			os.unlink(hardlink_tmp)
		except OSError as e:
			if e.errno != errno.ENOENT:
				writemsg(_("!!! Failed to remove hardlink temp file: %s\n") % \
					(hardlink_tmp,), noiselevel=-1)
				writemsg("!!! %s\n" % (e,), noiselevel=-1)
				return None
			del e
		for hardlink_src in hardlink_candidates:
			try:
				os.link(hardlink_src, hardlink_tmp)
			except OSError:
				continue
			else:
				try:
					os.rename(hardlink_tmp, dest)
				except OSError as e:
					writemsg(_("!!! Failed to rename %s to %s\n") % \
						(hardlink_tmp, dest), noiselevel=-1)
					writemsg("!!! %s\n" % (e,), noiselevel=-1)
					return None
				hardlinked = True
				break

	renamefailed=1
	if hardlinked:
		renamefailed = False
	if not hardlinked and (selinux_enabled or sstat.st_dev == dstat.st_dev):
		try:
			if selinux_enabled:
				ret = selinux.rename(src, dest)
			else:
				ret=os.rename(src,dest)
			renamefailed=0
		except SystemExit as e:
			raise
		except Exception as e:
			if e[0]!=errno.EXDEV:
				# Some random error.
				print(_("!!! Failed to move %(src)s to %(dest)s") % {"src": src, "dest": dest})
				print("!!!",e)
				return None
			# Invalid cross-device-link 'bind' mounted or actually Cross-Device
	if renamefailed:
		didcopy=0
		if stat.S_ISREG(sstat[stat.ST_MODE]):
			try: # For safety copy then move it over.
				if selinux_enabled:
					selinux.copyfile(src, dest + "#new")
					selinux.rename(dest + "#new", dest)
				else:
					shutil.copyfile(src,dest+"#new")
					os.rename(dest+"#new",dest)
				didcopy=1
			except SystemExit as e:
				raise
			except Exception as e:
				print(_('!!! copy %(src)s -> %(dest)s failed.') % {"src": src, "dest": dest})
				print("!!!",e)
				return None
		else:
			#we don't yet handle special, so we need to fall back to /bin/mv
			a = process.spawn([MOVE_BINARY, '-f', src, dest], env=os.environ)
			if a != os.EX_OK:
				writemsg(_("!!! Failed to move special file:\n"), noiselevel=-1)
				writemsg(_("!!! '%(src)s' to '%(dest)s'\n") % \
					{"src": _unicode_decode(src, encoding=encoding),
					"dest": _unicode_decode(dest, encoding=encoding)}, noiselevel=-1)
				writemsg("!!! %s\n" % a, noiselevel=-1)
				return None # failure
		try:
			if didcopy:
				if stat.S_ISLNK(sstat[stat.ST_MODE]):
					lchown(dest,sstat[stat.ST_UID],sstat[stat.ST_GID])
				else:
					os.chown(dest,sstat[stat.ST_UID],sstat[stat.ST_GID])
				os.chmod(dest, stat.S_IMODE(sstat[stat.ST_MODE])) # Sticky is reset on chown
				os.unlink(src)
		except SystemExit as e:
			raise
		except Exception as e:
			print(_("!!! Failed to chown/chmod/unlink in movefile()"))
			print("!!!",dest)
			print("!!!",e)
			return None

	try:
		if hardlinked:
			newmtime = long(os.stat(dest).st_mtime)
		else:
			if newmtime is not None:
				os.utime(dest, (newmtime, newmtime))
			else:
				os.utime(dest, (sstat.st_atime, sstat.st_mtime))
				newmtime = long(sstat.st_mtime)
	except OSError:
		# The utime can fail here with EPERM even though the move succeeded.
		# Instead of failing, use stat to return the mtime if possible.
		try:
			newmtime = long(os.stat(dest).st_mtime)
		except OSError as e:
			writemsg(_("!!! Failed to stat in movefile()\n"), noiselevel=-1)
			writemsg("!!! %s\n" % dest, noiselevel=-1)
			writemsg("!!! %s\n" % str(e), noiselevel=-1)
			return None

	if bsd_chflags:
		# Restore the flags we saved before moving
		if pflags:
			bsd_chflags.chflags(os.path.dirname(dest), pflags)

	return newmtime

def merge(mycat, mypkg, pkgloc, infloc, myroot, mysettings, myebuild=None,
	mytree=None, mydbapi=None, vartree=None, prev_mtimes=None, blockers=None,
	scheduler=None):
	if not os.access(myroot, os.W_OK):
		writemsg(_("Permission denied: access('%s', W_OK)\n") % myroot,
			noiselevel=-1)
		return errno.EACCES
	mylink = dblink(mycat, mypkg, myroot, mysettings, treetype=mytree,
		vartree=vartree, blockers=blockers, scheduler=scheduler)
	return mylink.merge(pkgloc, infloc, myroot, myebuild,
		mydbapi=mydbapi, prev_mtimes=prev_mtimes)

def unmerge(cat, pkg, myroot, mysettings, mytrimworld=1, vartree=None,
	ldpath_mtimes=None, scheduler=None):
	mylink = dblink(cat, pkg, myroot, mysettings, treetype="vartree",
		vartree=vartree, scheduler=scheduler)
	vartree = mylink.vartree
	try:
		mylink.lockdb()
		if mylink.exists():
			vartree.dbapi.plib_registry.load()
			vartree.dbapi.plib_registry.pruneNonExisting()
			retval = mylink.unmerge(trimworld=mytrimworld, cleanup=1,
				ldpath_mtimes=ldpath_mtimes)
			if retval == os.EX_OK:
				mylink.delete()
			return retval
		return os.EX_OK
	finally:
		vartree.dbapi.linkmap._clear_cache()
		mylink.unlockdb()

def dep_virtual(mysplit, mysettings):
	"Does virtual dependency conversion"
	newsplit=[]
	myvirtuals = mysettings.getvirtuals()
	for x in mysplit:
		if isinstance(x, list):
			newsplit.append(dep_virtual(x, mysettings))
		else:
			mykey=dep_getkey(x)
			mychoices = myvirtuals.get(mykey, None)
			if mychoices:
				if len(mychoices) == 1:
					a = x.replace(mykey, dep_getkey(mychoices[0]), 1)
				else:
					if x[0]=="!":
						# blocker needs "and" not "or(||)".
						a=[]
					else:
						a=['||']
					for y in mychoices:
						a.append(x.replace(mykey, dep_getkey(y), 1))
				newsplit.append(a)
			else:
				newsplit.append(x)
	return newsplit

def _expand_new_virtuals(mysplit, edebug, mydbapi, mysettings, myroot="/",
	trees=None, use_mask=None, use_force=None, **kwargs):
	"""Recursively expand new-style virtuals so as to collapse one or more
	levels of indirection.  In dep_zapdeps, new-style virtuals will be assigned
	zero cost regardless of whether or not they are currently installed. Virtual
	blockers are supported but only when the virtual expands to a single
	atom because it wouldn't necessarily make sense to block all the components
	of a compound virtual.  When more than one new-style virtual is matched,
	the matches are sorted from highest to lowest versions and the atom is
	expanded to || ( highest match ... lowest match )."""
	newsplit = []
	mytrees = trees[myroot]
	portdb = mytrees["porttree"].dbapi
	atom_graph = mytrees.get("atom_graph")
	parent = mytrees.get("parent")
	virt_parent = mytrees.get("virt_parent")
	graph_parent = None
	eapi = None
	if parent is not None:
		if virt_parent is not None:
			graph_parent = virt_parent
			eapi = virt_parent[0].metadata['EAPI']
		else:
			graph_parent = parent
			eapi = parent.metadata["EAPI"]
	repoman = not mysettings.local_config
	if kwargs["use_binaries"]:
		portdb = trees[myroot]["bintree"].dbapi
	myvirtuals = mysettings.getvirtuals()
	pprovideddict = mysettings.pprovideddict
	myuse = kwargs["myuse"]
	for x in mysplit:
		if x == "||":
			newsplit.append(x)
			continue
		elif isinstance(x, list):
			newsplit.append(_expand_new_virtuals(x, edebug, mydbapi,
				mysettings, myroot=myroot, trees=trees, use_mask=use_mask,
				use_force=use_force, **kwargs))
			continue

		if not isinstance(x, portage.dep.Atom):
			try:
				x = portage.dep.Atom(x)
			except portage.exception.InvalidAtom:
				if portage.dep._dep_check_strict:
					raise portage.exception.ParseError(
						_("invalid atom: '%s'") % x)
				else:
					# Only real Atom instances are allowed past this point.
					continue
			else:
				if x.blocker and x.blocker.overlap.forbid and \
					eapi in ("0", "1") and portage.dep._dep_check_strict:
					raise portage.exception.ParseError(
						_("invalid atom: '%s'") % (x,))
				if x.use and eapi in ("0", "1") and \
					portage.dep._dep_check_strict:
					raise portage.exception.ParseError(
						_("invalid atom: '%s'") % (x,))

		if repoman and x.use and x.use.conditional:
			evaluated_atom = portage.dep.remove_slot(x)
			if x.slot:
				evaluated_atom += ":%s" % x.slot
			evaluated_atom += str(x.use._eval_qa_conditionals(
				use_mask, use_force))
			x = portage.dep.Atom(evaluated_atom)

		if not repoman and \
			myuse is not None and isinstance(x, portage.dep.Atom) and x.use:
			if x.use.conditional:
				evaluated_atom = portage.dep.remove_slot(x)
				if x.slot:
					evaluated_atom += ":%s" % x.slot
				evaluated_atom += str(x.use.evaluate_conditionals(myuse))
				x = portage.dep.Atom(evaluated_atom)

		mykey = x.cp
		if not mykey.startswith("virtual/"):
			newsplit.append(x)
			if atom_graph is not None:
				atom_graph.add(x, graph_parent)
			continue
		mychoices = myvirtuals.get(mykey, [])
		if x.blocker:
			# Virtual blockers are no longer expanded here since
			# the un-expanded virtual atom is more useful for
			# maintaining a cache of blocker atoms.
			newsplit.append(x)
			if atom_graph is not None:
				atom_graph.add(x, graph_parent)
			continue

		if repoman or not hasattr(portdb, 'match_pkgs'):
			if portdb.cp_list(x.cp):
				newsplit.append(x)
			else:
				# TODO: Add PROVIDE check for repoman.
				a = []
				for y in mychoices:
					a.append(dep.Atom(x.replace(x.cp, y.cp, 1)))
				if not a:
					newsplit.append(x)
				elif len(a) == 1:
					newsplit.append(a[0])
				else:
					newsplit.append(['||'] + a)
			continue

		pkgs = []
		# Ignore USE deps here, since otherwise we might not
		# get any matches. Choices with correct USE settings
		# will be preferred in dep_zapdeps().
		matches = portdb.match_pkgs(x.without_use)
		# Use descending order to prefer higher versions.
		matches.reverse()
		for pkg in matches:
			# only use new-style matches
			if pkg.cp.startswith("virtual/"):
				pkgs.append(pkg)
		if not (pkgs or mychoices):
			# This one couldn't be expanded as a new-style virtual.  Old-style
			# virtuals have already been expanded by dep_virtual, so this one
			# is unavailable and dep_zapdeps will identify it as such.  The
			# atom is not eliminated here since it may still represent a
			# dependency that needs to be satisfied.
			newsplit.append(x)
			if atom_graph is not None:
				atom_graph.add(x, graph_parent)
			continue

		a = []
		for pkg in pkgs:
			virt_atom = '=' + pkg.cpv
			if x.use:
				virt_atom += str(x.use)
			virt_atom = dep.Atom(virt_atom)
			# According to GLEP 37, RDEPEND is the only dependency
			# type that is valid for new-style virtuals. Repoman
			# should enforce this.
			depstring = pkg.metadata['RDEPEND']
			pkg_kwargs = kwargs.copy()
			pkg_kwargs["myuse"] = pkg.use.enabled
			if edebug:
				util.writemsg_level(_("Virtual Parent:      %s\n") \
					% (pkg,), noiselevel=-1, level=logging.DEBUG)
				util.writemsg_level(_("Virtual Depstring:   %s\n") \
					% (depstring,), noiselevel=-1, level=logging.DEBUG)

			# Set EAPI used for validation in dep_check() recursion.
			mytrees["virt_parent"] = (pkg, virt_atom)

			try:
				mycheck = dep_check(depstring, mydbapi, mysettings,
					myroot=myroot, trees=trees, **pkg_kwargs)
			finally:
				# Restore previous EAPI after recursion.
				if virt_parent is not None:
					mytrees["virt_parent"] = virt_parent
				else:
					del mytrees["virt_parent"]

			if not mycheck[0]:
				raise portage.exception.ParseError(
					"%s: %s '%s'" % (y[0], mycheck[1], depstring))

			# pull in the new-style virtual
			mycheck[1].append(virt_atom)
			a.append(mycheck[1])
			if atom_graph is not None:
				atom_graph.add(virt_atom, graph_parent)
		# Plain old-style virtuals.  New-style virtuals are preferred.
		if not pkgs:
				for y in mychoices:
					new_atom = dep.Atom(x.replace(x.cp, y.cp, 1))
					matches = portdb.match(new_atom)
					# portdb is an instance of depgraph._dep_check_composite_db, so
					# USE conditionals are already evaluated.
					if matches and mykey in \
						portdb.aux_get(matches[-1], ['PROVIDE'])[0].split():
						a.append(new_atom)
						if atom_graph is not None:
							atom_graph.add(new_atom, graph_parent)

		if not a and mychoices:
			# Check for a virtual package.provided match.
			for y in mychoices:
				new_atom = dep.Atom(x.replace(x.cp, y.cp, 1))
				if match_from_list(new_atom,
					pprovideddict.get(new_atom.cp, [])):
					a.append(new_atom)
					if atom_graph is not None:
						atom_graph.add(new_atom, graph_parent)

		if not a:
			newsplit.append(x)
			if atom_graph is not None:
				atom_graph.add(x, graph_parent)
		elif len(a) == 1:
			newsplit.append(a[0])
		else:
			newsplit.append(['||'] + a)

	return newsplit

def dep_eval(deplist):
	if not deplist:
		return 1
	if deplist[0]=="||":
		#or list; we just need one "1"
		for x in deplist[1:]:
			if isinstance(x, list):
				if dep_eval(x)==1:
					return 1
			elif x==1:
					return 1
		#XXX: unless there's no available atoms in the list
		#in which case we need to assume that everything is
		#okay as some ebuilds are relying on an old bug.
		if len(deplist) == 1:
			return 1
		return 0
	else:
		for x in deplist:
			if isinstance(x, list):
				if dep_eval(x)==0:
					return 0
			elif x==0 or x==2:
				return 0
		return 1

def dep_zapdeps(unreduced, reduced, myroot, use_binaries=0, trees=None):
	"""Takes an unreduced and reduced deplist and removes satisfied dependencies.
	Returned deplist contains steps that must be taken to satisfy dependencies."""
	if trees is None:
		global db
		trees = db
	writemsg("ZapDeps -- %s\n" % (use_binaries), 2)
	if not reduced or unreduced == ["||"] or dep_eval(reduced):
		return []

	if unreduced[0] != "||":
		unresolved = []
		for x, satisfied in zip(unreduced, reduced):
			if isinstance(x, list):
				unresolved += dep_zapdeps(x, satisfied, myroot,
					use_binaries=use_binaries, trees=trees)
			elif not satisfied:
				unresolved.append(x)
		return unresolved

	# We're at a ( || atom ... ) type level and need to make a choice
	deps = unreduced[1:]
	satisfieds = reduced[1:]

	# Our preference order is for an the first item that:
	# a) contains all unmasked packages with the same key as installed packages
	# b) contains all unmasked packages
	# c) contains masked installed packages
	# d) is the first item

	preferred_installed = []
	preferred_in_graph = []
	preferred_any_slot = []
	preferred_non_installed = []
	unsat_use_in_graph = []
	unsat_use_installed = []
	unsat_use_non_installed = []
	other = []

	# Alias the trees we'll be checking availability against
	parent   = trees[myroot].get("parent")
	priority = trees[myroot].get("priority")
	graph_db = trees[myroot].get("graph_db")
	vardb = None
	if "vartree" in trees[myroot]:
		vardb = trees[myroot]["vartree"].dbapi
	if use_binaries:
		mydbapi = trees[myroot]["bintree"].dbapi
	else:
		mydbapi = trees[myroot]["porttree"].dbapi

	# Sort the deps into installed, not installed but already 
	# in the graph and other, not installed and not in the graph
	# and other, with values of [[required_atom], availablility]
	for x, satisfied in zip(deps, satisfieds):
		if isinstance(x, list):
			atoms = dep_zapdeps(x, satisfied, myroot,
				use_binaries=use_binaries, trees=trees)
		else:
			atoms = [x]
		if not vardb:
			# called by repoman
			other.append((atoms, None, False))
			continue

		all_available = True
		all_use_satisfied = True
		versions = {}
		for atom in atoms:
			if atom.blocker:
				continue
			# Ignore USE dependencies here since we don't want USE
			# settings to adversely affect || preference evaluation.
			avail_pkg = mydbapi.match(atom.without_use)
			if avail_pkg:
				avail_pkg = avail_pkg[-1] # highest (ascending order)
				avail_slot = dep.Atom("%s:%s" % (atom.cp,
					mydbapi.aux_get(avail_pkg, ["SLOT"])[0]))
			if not avail_pkg:
				all_available = False
				all_use_satisfied = False
				break

			if atom.use:
				avail_pkg_use = mydbapi.match(atom)
				if not avail_pkg_use:
					all_use_satisfied = False
				else:
					# highest (ascending order)
					avail_pkg_use = avail_pkg_use[-1]
					if avail_pkg_use != avail_pkg:
						avail_pkg = avail_pkg_use
						avail_slot = dep.Atom("%s:%s" % (atom.cp,
							mydbapi.aux_get(avail_pkg, ["SLOT"])[0]))

			versions[avail_slot] = avail_pkg

		this_choice = (atoms, versions, all_available)
		if all_available:
			# The "all installed" criterion is not version or slot specific.
			# If any version of a package is already in the graph then we
			# assume that it is preferred over other possible packages choices.
			all_installed = True
			for atom in set(dep.Atom(atom.cp) for atom in atoms \
				if not atom.blocker):
				# New-style virtuals have zero cost to install.
				if not vardb.match(atom) and not atom.startswith("virtual/"):
					all_installed = False
					break
			all_installed_slots = False
			if all_installed:
				all_installed_slots = True
				for slot_atom in versions:
					# New-style virtuals have zero cost to install.
					if not vardb.match(slot_atom) and \
						not slot_atom.startswith("virtual/"):
						all_installed_slots = False
						break
			if graph_db is None:
				if all_use_satisfied:
					if all_installed:
						if all_installed_slots:
							preferred_installed.append(this_choice)
						else:
							preferred_any_slot.append(this_choice)
					else:
						preferred_non_installed.append(this_choice)
				else:
					if all_installed_slots:
						unsat_use_installed.append(this_choice)
					else:
						unsat_use_non_installed.append(this_choice)
			else:
				all_in_graph = True
				for slot_atom in versions:
					# New-style virtuals have zero cost to install.
					if not graph_db.match(slot_atom) and \
						not slot_atom.startswith("virtual/"):
						all_in_graph = False
						break
				circular_atom = None
				if all_in_graph:
					if parent is None or priority is None:
						pass
					elif priority.buildtime:
						# Check if the atom would result in a direct circular
						# dependency and try to avoid that if it seems likely
						# to be unresolvable. This is only relevant for
						# buildtime deps that aren't already satisfied by an
						# installed package.
						cpv_slot_list = [parent]
						for atom in atoms:
							if atom.blocker:
								continue
							if vardb.match(atom):
								# If the atom is satisfied by an installed
								# version then it's not a circular dep.
								continue
							if atom.cp != parent.cp:
								continue
							if match_from_list(atom, cpv_slot_list):
								circular_atom = atom
								break
				if circular_atom is not None:
					other.append(this_choice)
				else:
					if all_use_satisfied:
						if all_in_graph:
							preferred_in_graph.append(this_choice)
						elif all_installed:
							if all_installed_slots:
								preferred_installed.append(this_choice)
							else:
								preferred_any_slot.append(this_choice)
						else:
							preferred_non_installed.append(this_choice)
					else:
						if all_in_graph:
							unsat_use_in_graph.append(this_choice)
						elif all_installed_slots:
							unsat_use_installed.append(this_choice)
						else:
							unsat_use_non_installed.append(this_choice)
		else:
			other.append(this_choice)

	# unsat_use_* must come after preferred_non_installed
	# for correct ordering in cases like || ( foo[a] foo[b] ).
	preferred = preferred_in_graph + preferred_installed + \
		preferred_any_slot + preferred_non_installed + \
		unsat_use_in_graph + unsat_use_installed + unsat_use_non_installed + \
		other

	for allow_masked in (False, True):
		for atoms, versions, all_available in preferred:
			if all_available or allow_masked:
				return atoms

	assert(False) # This point should not be reachable

def dep_expand(mydep, mydb=None, use_cache=1, settings=None):
	'''
	@rtype: Atom
	'''
	if not len(mydep):
		return mydep
	if mydep[0]=="*":
		mydep=mydep[1:]
	orig_dep = mydep
	if isinstance(orig_dep, dep.Atom):
		mydep = orig_dep.cp
	else:
		mydep = orig_dep
		has_cat = '/' in orig_dep
		if not has_cat:
			alphanum = re.search(r'\w', orig_dep)
			if alphanum:
				mydep = orig_dep[:alphanum.start()] + "null/" + \
					orig_dep[alphanum.start():]
		try:
			mydep = dep.Atom(mydep)
		except exception.InvalidAtom:
			# Missing '=' prefix is allowed for backward compatibility.
			if not dep.isvalidatom("=" + mydep):
				raise
			mydep = dep.Atom('=' + mydep)
			orig_dep = '=' + orig_dep
		if not has_cat:
			null_cat, pn = catsplit(mydep.cp)
			mydep = pn
		else:
			mydep = mydep.cp
	expanded = cpv_expand(mydep, mydb=mydb,
		use_cache=use_cache, settings=settings)
	return portage.dep.Atom(orig_dep.replace(mydep, expanded, 1))

def dep_check(depstring, mydbapi, mysettings, use="yes", mode=None, myuse=None,
	use_cache=1, use_binaries=0, myroot="/", trees=None):
	"""Takes a depend string and parses the condition."""
	edebug = mysettings.get("PORTAGE_DEBUG", None) == "1"
	#check_config_instance(mysettings)
	if trees is None:
		trees = globals()["db"]
	if use=="yes":
		if myuse is None:
			#default behavior
			myusesplit = mysettings["PORTAGE_USE"].split()
		else:
			myusesplit = myuse
			# We've been given useflags to use.
			#print "USE FLAGS PASSED IN."
			#print myuse
			#if "bindist" in myusesplit:
			#	print "BINDIST is set!"
			#else:
			#	print "BINDIST NOT set."
	else:
		#we are being run by autouse(), don't consult USE vars yet.
		# WE ALSO CANNOT USE SETTINGS
		myusesplit=[]

	#convert parenthesis to sublists
	try:
		mysplit = portage.dep.paren_reduce(depstring)
	except portage.exception.InvalidDependString as e:
		return [0, str(e)]

	mymasks = set()
	useforce = set()
	useforce.add(mysettings["ARCH"])
	if use == "all":
		# This masking/forcing is only for repoman.  In other cases, relevant
		# masking/forcing should have already been applied via
		# config.regenerate().  Also, binary or installed packages may have
		# been built with flags that are now masked, and it would be
		# inconsistent to mask them now.  Additionally, myuse may consist of
		# flags from a parent package that is being merged to a $ROOT that is
		# different from the one that mysettings represents.
		mymasks.update(mysettings.usemask)
		mymasks.update(mysettings.archlist())
		mymasks.discard(mysettings["ARCH"])
		useforce.update(mysettings.useforce)
		useforce.difference_update(mymasks)
	try:
		mysplit = portage.dep.use_reduce(mysplit, uselist=myusesplit,
			masklist=mymasks, matchall=(use=="all"), excludeall=useforce)
	except portage.exception.InvalidDependString as e:
		return [0, str(e)]

	# Do the || conversions
	mysplit=portage.dep.dep_opconvert(mysplit)

	if mysplit == []:
		#dependencies were reduced to nothing
		return [1,[]]

	# Recursively expand new-style virtuals so as to
	# collapse one or more levels of indirection.
	try:
		mysplit = _expand_new_virtuals(mysplit, edebug, mydbapi, mysettings,
			use=use, mode=mode, myuse=myuse,
			use_force=useforce, use_mask=mymasks, use_cache=use_cache,
			use_binaries=use_binaries, myroot=myroot, trees=trees)
	except portage.exception.ParseError as e:
		return [0, str(e)]

	mysplit2=mysplit[:]
	mysplit2=dep_wordreduce(mysplit2,mysettings,mydbapi,mode,use_cache=use_cache)
	if mysplit2 is None:
		return [0, _("Invalid token")]

	writemsg("\n\n\n", 1)
	writemsg("mysplit:  %s\n" % (mysplit), 1)
	writemsg("mysplit2: %s\n" % (mysplit2), 1)

	try:
		selected_atoms = dep_zapdeps(mysplit, mysplit2, myroot,
			use_binaries=use_binaries, trees=trees)
	except portage.exception.InvalidAtom as e:
		if portage.dep._dep_check_strict:
			raise # This shouldn't happen.
		# dbapi.match() failed due to an invalid atom in
		# the dependencies of an installed package.
		return [0, _("Invalid atom: '%s'") % (e,)]

	return [1, selected_atoms]

def dep_wordreduce(mydeplist,mysettings,mydbapi,mode,use_cache=1):
	"Reduces the deplist to ones and zeros"
	deplist=mydeplist[:]
	for mypos, token in enumerate(deplist):
		if isinstance(deplist[mypos], list):
			#recurse
			deplist[mypos]=dep_wordreduce(deplist[mypos],mysettings,mydbapi,mode,use_cache=use_cache)
		elif deplist[mypos]=="||":
			pass
		elif token[:1] == "!":
			deplist[mypos] = False
		else:
			mykey = deplist[mypos].cp
			if mysettings and mykey in mysettings.pprovideddict and \
			        match_from_list(deplist[mypos], mysettings.pprovideddict[mykey]):
				deplist[mypos]=True
			elif mydbapi is None:
				# Assume nothing is satisfied.  This forces dep_zapdeps to
				# return all of deps the deps that have been selected
				# (excluding those satisfied by package.provided).
				deplist[mypos] = False
			else:
				if mode:
					x = mydbapi.xmatch(mode, deplist[mypos])
					if mode.startswith("minimum-"):
						mydep = []
						if x:
							mydep.append(x)
					else:
						mydep = x
				else:
					mydep=mydbapi.match(deplist[mypos],use_cache=use_cache)
				if mydep!=None:
					tmp=(len(mydep)>=1)
					if deplist[mypos][0]=="!":
						tmp=False
					deplist[mypos]=tmp
				else:
					#encountered invalid string
					return None
	return deplist

_cpv_key_re = re.compile('^' + versions._cpv + '$', re.VERBOSE)
def cpv_getkey(mycpv):
	"""Calls pkgsplit on a cpv and returns only the cp."""
	m = _cpv_key_re.match(mycpv)
	if m is not None:
		return m.group(2)

	warnings.warn("portage.cpv_getkey() called with invalid cpv: '%s'" \
		% (mycpv,), DeprecationWarning)

	myslash = mycpv.split("/", 1)
	mysplit = versions._pkgsplit(myslash[-1])
	if mysplit is None:
		return None
	mylen=len(myslash)
	if mylen==2:
		return myslash[0]+"/"+mysplit[0]
	else:
		return mysplit[0]

getCPFromCPV = cpv_getkey

def key_expand(mykey, mydb=None, use_cache=1, settings=None):
	"""This is deprecated because it just returns the first match instead of
	raising AmbiguousPackageName like cpv_expand does."""
	warnings.warn("portage.key_expand() is deprecated", DeprecationWarning)
	mysplit=mykey.split("/")
	if settings is None:
		settings = globals()["settings"]
	virts = settings.getvirtuals("/")
	virts_p = settings.get_virts_p("/")
	if len(mysplit)==1:
		if hasattr(mydb, "cp_list"):
			for x in mydb.categories:
				if mydb.cp_list(x+"/"+mykey,use_cache=use_cache):
					return dep.Atom(x + "/" + mykey)
			if mykey in virts_p:
				return(virts_p[mykey][0])
		return dep.Atom("null/" + mykey)
	elif mydb:
		if hasattr(mydb, "cp_list"):
			if not mydb.cp_list(mykey, use_cache=use_cache) and \
				virts and mykey in virts:
				return virts[mykey][0]
		if not isinstance(mykey, dep.Atom):
			mykey = dep.Atom(mykey)
		return mykey

def cpv_expand(mycpv, mydb=None, use_cache=1, settings=None):
	"""Given a string (packagename or virtual) expand it into a valid
	cat/package string. Virtuals use the mydb to determine which provided
	virtual is a valid choice and defaults to the first element when there
	are no installed/available candidates."""
	myslash=mycpv.split("/")
	mysplit = versions._pkgsplit(myslash[-1])
	if settings is None:
		settings = globals()["settings"]
	virts = settings.getvirtuals("/")
	virts_p = settings.get_virts_p("/")
	if len(myslash)>2:
		# this is illegal case.
		mysplit=[]
		mykey=mycpv
	elif len(myslash)==2:
		if mysplit:
			mykey=myslash[0]+"/"+mysplit[0]
		else:
			mykey=mycpv
		if mydb and virts and mykey in virts:
			writemsg("mydb.__class__: %s\n" % (mydb.__class__), 1)
			if hasattr(mydb, "cp_list"):
				if not mydb.cp_list(mykey, use_cache=use_cache):
					writemsg("virts[%s]: %s\n" % (str(mykey),virts[mykey]), 1)
					mykey_orig = mykey[:]
					for vkey in virts[mykey]:
						# The virtuals file can contain a versioned atom, so
						# it may be necessary to remove the operator and
						# version from the atom before it is passed into
						# dbapi.cp_list().
						if mydb.cp_list(dep_getkey(vkey), use_cache=use_cache):
							mykey = str(vkey)
							writemsg(_("virts chosen: %s\n") % (mykey), 1)
							break
					if mykey == mykey_orig:
						mykey = str(virts[mykey][0])
						writemsg(_("virts defaulted: %s\n") % (mykey), 1)
			#we only perform virtual expansion if we are passed a dbapi
	else:
		#specific cpv, no category, ie. "foo-1.0"
		if mysplit:
			myp=mysplit[0]
		else:
			# "foo" ?
			myp=mycpv
		mykey=None
		matches=[]
		if mydb and hasattr(mydb, "categories"):
			for x in mydb.categories:
				if mydb.cp_list(x+"/"+myp,use_cache=use_cache):
					matches.append(x+"/"+myp)
		if len(matches) > 1:
			virtual_name_collision = False
			if len(matches) == 2:
				for x in matches:
					if not x.startswith("virtual/"):
						# Assume that the non-virtual is desired.  This helps
						# avoid the ValueError for invalid deps that come from
						# installed packages (during reverse blocker detection,
						# for example).
						mykey = x
					else:
						virtual_name_collision = True
			if not virtual_name_collision:
				# AmbiguousPackageName inherits from ValueError,
				# for backward compatibility with calling code
				# that already handles ValueError.
				raise portage.exception.AmbiguousPackageName(matches)
		elif matches:
			mykey=matches[0]

		if not mykey and not isinstance(mydb, list):
			if myp in virts_p:
				mykey=virts_p[myp][0]
			#again, we only perform virtual expansion if we have a dbapi (not a list)
		if not mykey:
			mykey="null/"+myp
	if mysplit:
		if mysplit[2]=="r0":
			return mykey+"-"+mysplit[1]
		else:
			return mykey+"-"+mysplit[1]+"-"+mysplit[2]
	else:
		return mykey

def getmaskingreason(mycpv, metadata=None, settings=None, portdb=None, return_location=False):
	from portage.util import grablines
	if settings is None:
		settings = globals()["settings"]
	if portdb is None:
		portdb = globals()["portdb"]
	mysplit = catpkgsplit(mycpv)
	if not mysplit:
		raise ValueError(_("invalid CPV: %s") % mycpv)
	if metadata is None:
		db_keys = list(portdb._aux_cache_keys)
		try:
			metadata = dict(zip(db_keys, portdb.aux_get(mycpv, db_keys)))
		except KeyError:
			if not portdb.cpv_exists(mycpv):
				raise
	if metadata is None:
		# Can't access SLOT due to corruption.
		cpv_slot_list = [mycpv]
	else:
		cpv_slot_list = ["%s:%s" % (mycpv, metadata["SLOT"])]
	mycp=mysplit[0]+"/"+mysplit[1]

	# XXX- This is a temporary duplicate of code from the config constructor.
	locations = [os.path.join(settings["PORTDIR"], "profiles")]
	locations.extend(settings.profiles)
	for ov in settings["PORTDIR_OVERLAY"].split():
		profdir = os.path.join(normalize_path(ov), "profiles")
		if os.path.isdir(profdir):
			locations.append(profdir)
	locations.append(os.path.join(settings["PORTAGE_CONFIGROOT"],
		USER_CONFIG_PATH))
	locations.reverse()
	pmasklists = [(x, grablines(os.path.join(x, "package.mask"), recursive=1)) for x in locations]

	if mycp in settings.pmaskdict:
		for x in settings.pmaskdict[mycp]:
			if match_from_list(x, cpv_slot_list):
				comment = ""
				l = "\n"
				comment_valid = -1
				for pmask in pmasklists:
					pmask_filename = os.path.join(pmask[0], "package.mask")
					for i in range(len(pmask[1])):
						l = pmask[1][i].strip()
						if l == "":
							comment = ""
							comment_valid = -1
						elif l[0] == "#":
							comment += (l+"\n")
							comment_valid = i + 1
						elif l == x:
							if comment_valid != i:
								comment = ""
							if return_location:
								return (comment, pmask_filename)
							else:
								return comment
						elif comment_valid != -1:
							# Apparently this comment applies to muliple masks, so
							# it remains valid until a blank line is encountered.
							comment_valid += 1
	if return_location:
		return (None, None)
	else:
		return None

def getmaskingstatus(mycpv, settings=None, portdb=None):
	if settings is None:
		settings = config(clone=globals()["settings"])
	if portdb is None:
		portdb = globals()["portdb"]

	metadata = None
	installed = False
	if not isinstance(mycpv, basestring):
		# emerge passed in a Package instance
		pkg = mycpv
		mycpv = pkg.cpv
		metadata = pkg.metadata
		installed = pkg.installed

	mysplit = catpkgsplit(mycpv)
	if not mysplit:
		raise ValueError(_("invalid CPV: %s") % mycpv)
	if metadata is None:
		db_keys = list(portdb._aux_cache_keys)
		try:
			metadata = dict(zip(db_keys, portdb.aux_get(mycpv, db_keys)))
		except KeyError:
			if not portdb.cpv_exists(mycpv):
				raise
			return ["corruption"]
		if "?" in metadata["LICENSE"]:
			settings.setcpv(mycpv, mydb=metadata)
			metadata["USE"] = settings["PORTAGE_USE"]
		else:
			metadata["USE"] = ""
	mycp=mysplit[0]+"/"+mysplit[1]

	rValue = []

	# profile checking
	if settings._getProfileMaskAtom(mycpv, metadata):
		rValue.append("profile")

	# package.mask checking
	if settings._getMaskAtom(mycpv, metadata):
		rValue.append("package.mask")

	# keywords checking
	eapi = metadata["EAPI"]
	mygroups = settings._getKeywords(mycpv, metadata)
	licenses = metadata["LICENSE"]
	properties = metadata["PROPERTIES"]
	slot = metadata["SLOT"]
	if eapi.startswith("-"):
		eapi = eapi[1:]
	if not eapi_is_supported(eapi):
		return ["EAPI %s" % eapi]
	elif _eapi_is_deprecated(eapi) and not installed:
		return ["EAPI %s" % eapi]
	egroups = settings.configdict["backupenv"].get(
		"ACCEPT_KEYWORDS", "").split()
	pgroups = settings["ACCEPT_KEYWORDS"].split()
	myarch = settings["ARCH"]
	if pgroups and myarch not in pgroups:
		"""For operating systems other than Linux, ARCH is not necessarily a
		valid keyword."""
		myarch = pgroups[0].lstrip("~")

	cp = dep_getkey(mycpv)
	pkgdict = settings.pkeywordsdict.get(cp)
	matches = False
	if pkgdict:
		cpv_slot_list = ["%s:%s" % (mycpv, metadata["SLOT"])]
		for atom, pkgkeywords in pkgdict.items():
			if match_from_list(atom, cpv_slot_list):
				matches = True
				pgroups.extend(pkgkeywords)
	if matches or egroups:
		pgroups.extend(egroups)
		inc_pgroups = set()
		for x in pgroups:
			if x.startswith("-"):
				if x == "-*":
					inc_pgroups.clear()
				else:
					inc_pgroups.discard(x[1:])
			else:
				inc_pgroups.add(x)
		pgroups = inc_pgroups
		del inc_pgroups

	kmask = "missing"

	if '**' in pgroups:
		kmask = None
	else:
		for keyword in pgroups:
			if keyword in mygroups:
				kmask = None
				break

	if kmask:
		fallback = None
		for gp in mygroups:
			if gp=="*":
				kmask=None
				break
			elif gp=="-"+myarch and myarch in pgroups:
				kmask="-"+myarch
				break
			elif gp=="~"+myarch and myarch in pgroups:
				kmask="~"+myarch
				break

	try:
		missing_licenses = settings._getMissingLicenses(mycpv, metadata)
		if missing_licenses:
			allowed_tokens = set(["||", "(", ")"])
			allowed_tokens.update(missing_licenses)
			license_split = licenses.split()
			license_split = [x for x in license_split \
				if x in allowed_tokens]
			msg = license_split[:]
			msg.append("license(s)")
			rValue.append(" ".join(msg))
	except portage.exception.InvalidDependString as e:
		rValue.append("LICENSE: "+str(e))

	try:
		missing_properties = settings._getMissingProperties(mycpv, metadata)
		if missing_properties:
			allowed_tokens = set(["||", "(", ")"])
			allowed_tokens.update(missing_properties)
			properties_split = properties.split()
			properties_split = [x for x in properties_split \
					if x in allowed_tokens]
			msg = properties_split[:]
			msg.append("properties")
			rValue.append(" ".join(msg))
	except portage.exception.InvalidDependString as e:
		rValue.append("PROPERTIES: "+str(e))

	# Only show KEYWORDS masks for installed packages
	# if they're not masked for any other reason.
	if kmask and (not installed or not rValue):
		rValue.append(kmask+" keyword")

	return rValue

auxdbkeys=[
  'DEPEND',    'RDEPEND',   'SLOT',      'SRC_URI',
	'RESTRICT',  'HOMEPAGE',  'LICENSE',   'DESCRIPTION',
	'KEYWORDS',  'INHERITED', 'IUSE', 'UNUSED_00',
	'PDEPEND',   'PROVIDE', 'EAPI',
	'PROPERTIES', 'DEFINED_PHASES', 'UNUSED_05', 'UNUSED_04',
	'UNUSED_03', 'UNUSED_02', 'UNUSED_01',
	]
auxdbkeylen=len(auxdbkeys)

from portage.dbapi import dbapi
from portage.dbapi.virtual import fakedbapi
from portage.dbapi.bintree import bindbapi, binarytree
from portage.dbapi.vartree import vardbapi, vartree, dblink
from portage.dbapi.porttree import close_portdbapi_caches, portdbapi, portagetree

class FetchlistDict(portage.cache.mappings.Mapping):
	"""This provide a mapping interface to retrieve fetch lists.  It's used
	to allow portage.manifest.Manifest to access fetch lists via a standard
	mapping interface rather than use the dbapi directly."""
	def __init__(self, pkgdir, settings, mydbapi):
		"""pkgdir is a directory containing ebuilds and settings is passed into
		portdbapi.getfetchlist for __getitem__ calls."""
		self.pkgdir = pkgdir
		self.cp = os.sep.join(pkgdir.split(os.sep)[-2:])
		self.settings = settings
		self.mytree = os.path.realpath(os.path.dirname(os.path.dirname(pkgdir)))
		self.portdb = mydbapi
	def __getitem__(self, pkg_key):
		"""Returns the complete fetch list for a given package."""
		return list(self.portdb.getFetchMap(pkg_key, mytree=self.mytree))
	def __contains__(self, cpv):
		return cpv in self.__iter__()
	def has_key(self, pkg_key):
		"""Returns true if the given package exists within pkgdir."""
		return pkg_key in self

	def __iter__(self):
		return iter(self.portdb.cp_list(self.cp, mytree=self.mytree))

	def __len__(self):
		"""This needs to be implemented in order to avoid
		infinite recursion in some cases."""
		return len(self.portdb.cp_list(self.cp, mytree=self.mytree))

	def keys(self):
		"""Returns keys for all packages within pkgdir"""
		return self.portdb.cp_list(self.cp, mytree=self.mytree)

	if sys.hexversion >= 0x3000000:
		keys = __iter__

def pkgmerge(mytbz2, myroot, mysettings, mydbapi=None,
	vartree=None, prev_mtimes=None, blockers=None):
	"""will merge a .tbz2 file, returning a list of runtime dependencies
		that must be satisfied, or None if there was a merge error.	This
		code assumes the package exists."""
	global db
	if mydbapi is None:
		mydbapi = db[myroot]["bintree"].dbapi
	if vartree is None:
		vartree = db[myroot]["vartree"]
	if mytbz2[-5:]!=".tbz2":
		print(_("!!! Not a .tbz2 file"))
		return 1

	tbz2_lock = None
	mycat = None
	mypkg = None
	did_merge_phase = False
	success = False
	try:
		""" Don't lock the tbz2 file because the filesytem could be readonly or
		shared by a cluster."""
		#tbz2_lock = portage.locks.lockfile(mytbz2, wantnewlockfile=1)

		mypkg = os.path.basename(mytbz2)[:-5]
		xptbz2 = portage.xpak.tbz2(mytbz2)
		mycat = xptbz2.getfile(_unicode_encode("CATEGORY",
			encoding=_encodings['repo.content']))
		if not mycat:
			writemsg(_("!!! CATEGORY info missing from info chunk, aborting...\n"),
				noiselevel=-1)
			return 1
		mycat = _unicode_decode(mycat,
			encoding=_encodings['repo.content'], errors='replace')
		mycat = mycat.strip()

		# These are the same directories that would be used at build time.
		builddir = os.path.join(
			mysettings["PORTAGE_TMPDIR"], "portage", mycat, mypkg)
		catdir = os.path.dirname(builddir)
		pkgloc = os.path.join(builddir, "image")
		infloc = os.path.join(builddir, "build-info")
		myebuild = os.path.join(
			infloc, os.path.basename(mytbz2)[:-4] + "ebuild")
		portage.util.ensure_dirs(os.path.dirname(catdir),
			uid=portage_uid, gid=portage_gid, mode=0o70, mask=0)
		catdir_lock = portage.locks.lockdir(catdir)
		portage.util.ensure_dirs(catdir,
			uid=portage_uid, gid=portage_gid, mode=0o70, mask=0)
		try:
			shutil.rmtree(builddir)
		except (IOError, OSError) as e:
			if e.errno != errno.ENOENT:
				raise
			del e
		for mydir in (builddir, pkgloc, infloc):
			portage.util.ensure_dirs(mydir, uid=portage_uid,
				gid=portage_gid, mode=0o755)
		writemsg_stdout(_(">>> Extracting info\n"))
		xptbz2.unpackinfo(infloc)
		mysettings.setcpv(mycat + "/" + mypkg, mydb=mydbapi)
		# Store the md5sum in the vdb.
		fp = open(_unicode_encode(os.path.join(infloc, 'BINPKGMD5')), 'w')
		fp.write(str(portage.checksum.perform_md5(mytbz2))+"\n")
		fp.close()

		# This gives bashrc users an opportunity to do various things
		# such as remove binary packages after they're installed.
		mysettings["PORTAGE_BINPKG_FILE"] = mytbz2
		mysettings.backup_changes("PORTAGE_BINPKG_FILE")
		debug = mysettings.get("PORTAGE_DEBUG", "") == "1"

		# Eventually we'd like to pass in the saved ebuild env here.
		retval = doebuild(myebuild, "setup", myroot, mysettings, debug=debug,
			tree="bintree", mydbapi=mydbapi, vartree=vartree)
		if retval != os.EX_OK:
			writemsg(_("!!! Setup failed: %s\n") % retval, noiselevel=-1)
			return retval

		writemsg_stdout(_(">>> Extracting %s\n") % mypkg)
		retval = portage.process.spawn_bash(
			"bzip2 -dqc -- '%s' | tar -xp -C '%s' -f -" % (mytbz2, pkgloc),
			env=mysettings.environ())
		if retval != os.EX_OK:
			writemsg(_("!!! Error Extracting '%s'\n") % mytbz2, noiselevel=-1)
			return retval
		#portage.locks.unlockfile(tbz2_lock)
		#tbz2_lock = None

		mylink = dblink(mycat, mypkg, myroot, mysettings, vartree=vartree,
			treetype="bintree", blockers=blockers)
		retval = mylink.merge(pkgloc, infloc, myroot, myebuild, cleanup=0,
			mydbapi=mydbapi, prev_mtimes=prev_mtimes)
		did_merge_phase = True
		success = retval == os.EX_OK
		return retval
	finally:
		mysettings.pop("PORTAGE_BINPKG_FILE", None)
		if tbz2_lock:
			portage.locks.unlockfile(tbz2_lock)
		if True:
			if not did_merge_phase:
				# The merge phase handles this already.  Callers don't know how
				# far this function got, so we have to call elog_process() here
				# so that it's only called once.
				from portage.elog import elog_process
				elog_process(mycat + "/" + mypkg, mysettings)
			try:
				if success:
					shutil.rmtree(builddir)
			except (IOError, OSError) as e:
				if e.errno != errno.ENOENT:
					raise
				del e

def deprecated_profile_check(settings=None):
	config_root = "/"
	if settings is not None:
		config_root = settings["PORTAGE_CONFIGROOT"]
	deprecated_profile_file = os.path.join(config_root,
		DEPRECATED_PROFILE_FILE)
	if not os.access(deprecated_profile_file, os.R_OK):
		return False
	dcontent = codecs.open(_unicode_encode(deprecated_profile_file,
		encoding=_encodings['fs'], errors='strict'), 
		mode='r', encoding=_encodings['content'], errors='replace').readlines()
	writemsg(colorize("BAD", _("\n!!! Your current profile is "
		"deprecated and not supported anymore.")) + "\n", noiselevel=-1)
	writemsg(colorize("BAD", _("!!! Use eselect profile to update your "
		"profile.")) + "\n", noiselevel=-1)
	if not dcontent:
		writemsg(colorize("BAD", _("!!! Please refer to the "
			"Gentoo Upgrading Guide.")) + "\n", noiselevel=-1)
		return True
	newprofile = dcontent[0]
	writemsg(colorize("BAD", _("!!! Please upgrade to the "
		"following profile if possible:")) + "\n", noiselevel=-1)
	writemsg(8*" " + colorize("GOOD", newprofile) + "\n", noiselevel=-1)
	if len(dcontent) > 1:
		writemsg(_("To upgrade do the following steps:\n"), noiselevel=-1)
		for myline in dcontent[1:]:
			writemsg(myline, noiselevel=-1)
		writemsg("\n\n", noiselevel=-1)
	return True

# gets virtual package settings
def getvirtuals(myroot):
	global settings
	writemsg("--- DEPRECATED call to getvirtual\n")
	return settings.getvirtuals(myroot)

def commit_mtimedb(mydict=None, filename=None):
	if mydict is None:
		global mtimedb
		if "mtimedb" not in globals() or mtimedb is None:
			return
		mtimedb.commit()
		return
	if filename is None:
		global mtimedbfile
		filename = mtimedbfile
	mydict["version"] = VERSION
	d = {} # for full backward compat, pickle it as a plain dict object.
	d.update(mydict)
	try:
		f = atomic_ofstream(filename, mode='wb')
		pickle.dump(d, f, protocol=2)
		f.close()
		portage.util.apply_secpass_permissions(filename,
			uid=uid, gid=portage_gid, mode=0o644)
	except (IOError, OSError) as e:
		pass

def portageexit():
	global uid,portage_gid,portdb,db
	if secpass and os.environ.get("SANDBOX_ON") != "1":
		close_portdbapi_caches()
		commit_mtimedb()

atexit_register(portageexit)

def _global_updates(trees, prev_mtimes):
	"""
	Perform new global updates if they exist in $PORTDIR/profiles/updates/.

	@param trees: A dictionary containing portage trees.
	@type trees: dict
	@param prev_mtimes: A dictionary containing mtimes of files located in
		$PORTDIR/profiles/updates/.
	@type prev_mtimes: dict
	@rtype: None or List
	@return: None if no were no updates, otherwise a list of update commands
		that have been performed.
	"""
	# only do this if we're root and not running repoman/ebuild digest
	global secpass
	if secpass < 2 or "SANDBOX_ACTIVE" in os.environ:
		return
	root = "/"
	mysettings = trees["/"]["vartree"].settings
	updpath = os.path.join(mysettings["PORTDIR"], "profiles", "updates")

	try:
		if mysettings["PORTAGE_CALLER"] == "fixpackages":
			update_data = grab_updates(updpath)
		else:
			update_data = grab_updates(updpath, prev_mtimes)
	except portage.exception.DirectoryNotFound:
		writemsg(_("--- 'profiles/updates' is empty or "
			"not available. Empty portage tree?\n"), noiselevel=1)
		return
	myupd = None
	if len(update_data) > 0:
		do_upgrade_packagesmessage = 0
		myupd = []
		timestamps = {}
		for mykey, mystat, mycontent in update_data:
			writemsg_stdout("\n\n")
			writemsg_stdout(colorize("GOOD",
				_("Performing Global Updates: "))+bold(mykey)+"\n")
			writemsg_stdout(_("(Could take a couple of minutes if you have a lot of binary packages.)\n"))
			writemsg_stdout(_("  %s='update pass'  %s='binary update'  "
				"%s='/var/db update'  %s='/var/db move'\n"
				"  %s='/var/db SLOT move'  %s='binary move'  "
				"%s='binary SLOT move'\n  %s='update /etc/portage/package.*'\n") % \
				(bold("."), bold("*"), bold("#"), bold("@"), bold("s"), bold("%"), bold("S"), bold("p")))
			valid_updates, errors = parse_updates(mycontent)
			myupd.extend(valid_updates)
			writemsg_stdout(len(valid_updates) * "." + "\n")
			if len(errors) == 0:
				# Update our internal mtime since we
				# processed all of our directives.
				timestamps[mykey] = long(mystat.st_mtime)
			else:
				for msg in errors:
					writemsg("%s\n" % msg, noiselevel=-1)

		world_file = os.path.join(root, WORLD_FILE)
		world_list = grabfile(world_file)
		world_modified = False
		for update_cmd in myupd:
			for pos, atom in enumerate(world_list):
				new_atom = update_dbentry(update_cmd, atom)
				if atom != new_atom:
					world_list[pos] = new_atom
					world_modified = True
		if world_modified:
			world_list.sort()
			write_atomic(world_file,
				"".join("%s\n" % (x,) for x in world_list))

		update_config_files("/",
			mysettings.get("CONFIG_PROTECT","").split(),
			mysettings.get("CONFIG_PROTECT_MASK","").split(),
			myupd)

		trees["/"]["bintree"] = binarytree("/", mysettings["PKGDIR"],
			settings=mysettings)
		vardb = trees["/"]["vartree"].dbapi
		bindb = trees["/"]["bintree"].dbapi
		if not os.access(bindb.bintree.pkgdir, os.W_OK):
			bindb = None
		for update_cmd in myupd:
			if update_cmd[0] == "move":
				moves = vardb.move_ent(update_cmd)
				if moves:
					writemsg_stdout(moves * "@")
				if bindb:
					moves = bindb.move_ent(update_cmd)
					if moves:
						writemsg_stdout(moves * "%")
			elif update_cmd[0] == "slotmove":
				moves = vardb.move_slot_ent(update_cmd)
				if moves:
					writemsg_stdout(moves * "s")
				if bindb:
					moves = bindb.move_slot_ent(update_cmd)
					if moves:
						writemsg_stdout(moves * "S")

		# The above global updates proceed quickly, so they
		# are considered a single mtimedb transaction.
		if len(timestamps) > 0:
			# We do not update the mtime in the mtimedb
			# until after _all_ of the above updates have
			# been processed because the mtimedb will
			# automatically commit when killed by ctrl C.
			for mykey, mtime in timestamps.items():
				prev_mtimes[mykey] = mtime

		# We gotta do the brute force updates for these now.
		if mysettings["PORTAGE_CALLER"] == "fixpackages" or \
		"fixpackages" in mysettings.features:
			def onUpdate(maxval, curval):
				if curval > 0:
					writemsg_stdout("#")
			vardb.update_ents(myupd, onUpdate=onUpdate)
			if bindb:
				def onUpdate(maxval, curval):
					if curval > 0:
						writemsg_stdout("*")
				bindb.update_ents(myupd, onUpdate=onUpdate)
		else:
			do_upgrade_packagesmessage = 1

		# Update progress above is indicated by characters written to stdout so
		# we print a couple new lines here to separate the progress output from
		# what follows.
		print()
		print()

		if do_upgrade_packagesmessage and bindb and \
			bindb.cpv_all():
			writemsg_stdout(_(" ** Skipping packages. Run 'fixpackages' or set it in FEATURES to fix the tbz2's in the packages directory.\n"))
			writemsg_stdout(bold(_("Note: This can take a very long time.")))
			writemsg_stdout("\n")
	if myupd:
		return myupd

#continue setting up other trees

class MtimeDB(dict):
	def __init__(self, filename):
		dict.__init__(self)
		self.filename = filename
		self._load(filename)

	def _load(self, filename):
		try:
			f = open(_unicode_encode(filename), 'rb')
			mypickle = pickle.Unpickler(f)
			try:
				mypickle.find_global = None
			except AttributeError:
				# TODO: If py3k, override Unpickler.find_class().
				pass
			d = mypickle.load()
			f.close()
			del f
		except (IOError, OSError, EOFError, ValueError, pickle.UnpicklingError) as e:
			if isinstance(e, pickle.UnpicklingError):
				writemsg(_("!!! Error loading '%s': %s\n") % \
					(filename, str(e)), noiselevel=-1)
			del e
			d = {}

		if "old" in d:
			d["updates"] = d["old"]
			del d["old"]
		if "cur" in d:
			del d["cur"]

		d.setdefault("starttime", 0)
		d.setdefault("version", "")
		for k in ("info", "ldpath", "updates"):
			d.setdefault(k, {})

		mtimedbkeys = set(("info", "ldpath", "resume", "resume_backup",
			"starttime", "updates", "version"))

		for k in list(d):
			if k not in mtimedbkeys:
				writemsg(_("Deleting invalid mtimedb key: %s\n") % str(k))
				del d[k]
		self.update(d)
		self._clean_data = copy.deepcopy(d)

	def commit(self):
		if not self.filename:
			return
		d = {}
		d.update(self)
		# Only commit if the internal state has changed.
		if d != self._clean_data:
			commit_mtimedb(mydict=d, filename=self.filename)
			self._clean_data = copy.deepcopy(d)

def create_trees(config_root=None, target_root=None, trees=None):
	if trees is None:
		trees = {}
	else:
		# clean up any existing portdbapi instances
		for myroot in trees:
			portdb = trees[myroot]["porttree"].dbapi
			portdb.close_caches()
			portdbapi.portdbapi_instances.remove(portdb)
			del trees[myroot]["porttree"], myroot, portdb

	settings = config(config_root=config_root, target_root=target_root,
		config_incrementals=portage.const.INCREMENTALS)
	settings.lock()

	myroots = [(settings["ROOT"], settings)]
	if settings["ROOT"] != "/":

		# When ROOT != "/" we only want overrides from the calling
		# environment to apply to the config that's associated
		# with ROOT != "/", so pass an empty dict for the env parameter.
		settings = config(config_root=None, target_root="/", env={})
		settings.lock()
		myroots.append((settings["ROOT"], settings))

	for myroot, mysettings in myroots:
		trees[myroot] = portage.util.LazyItemsDict(trees.get(myroot, {}))
		trees[myroot].addLazySingleton("virtuals", mysettings.getvirtuals, myroot)
		trees[myroot].addLazySingleton(
			"vartree", vartree, myroot, categories=mysettings.categories,
				settings=mysettings)
		trees[myroot].addLazySingleton("porttree",
			portagetree, myroot, settings=mysettings)
		trees[myroot].addLazySingleton("bintree",
			binarytree, myroot, mysettings["PKGDIR"], settings=mysettings)
	return trees

class _LegacyGlobalProxy(proxy.objectproxy.ObjectProxy):
	"""
	Instances of these serve as proxies to global variables
	that are initialized on demand.
	"""

	__slots__ = ('_name',)

	def __init__(self, name):
		proxy.objectproxy.ObjectProxy.__init__(self)
		object.__setattr__(self, '_name', name)

	def _get_target(self):
		init_legacy_globals()
		name = object.__getattribute__(self, '_name')
		return globals()[name]

class _PortdbProxy(proxy.objectproxy.ObjectProxy):
	"""
	The portdb is initialized separately from the rest
	of the variables, since sometimes the other variables
	are needed while the portdb is not.
	"""

	__slots__ = ()

	def _get_target(self):
		init_legacy_globals()
		global db, portdb, root, _portdb_initialized
		if not _portdb_initialized:
			portdb = db[root]["porttree"].dbapi
			_portdb_initialized = True
		return portdb

class _MtimedbProxy(proxy.objectproxy.ObjectProxy):
	"""
	The mtimedb is independent from the portdb and other globals.
	"""

	__slots__ = ('_name',)

	def __init__(self, name):
		proxy.objectproxy.ObjectProxy.__init__(self)
		object.__setattr__(self, '_name', name)

	def _get_target(self):
		global mtimedb, mtimedbfile, _mtimedb_initialized
		if not _mtimedb_initialized:
			mtimedbfile = os.path.join(os.path.sep,
				CACHE_PATH, "mtimedb")
			mtimedb = MtimeDB(mtimedbfile)
			_mtimedb_initialized = True
		name = object.__getattribute__(self, '_name')
		return globals()[name]

_legacy_global_var_names = ("archlist", "db", "features",
	"groups", "mtimedb", "mtimedbfile", "pkglines",
	"portdb", "profiledir", "root", "selinux_enabled",
	"settings", "thirdpartymirrors", "usedefaults")

def _disable_legacy_globals():
	"""
	This deletes the ObjectProxy instances that are used
	for lazy initialization of legacy global variables.
	The purpose of deleting them is to prevent new code
	from referencing these deprecated variables.
	"""
	global _legacy_global_var_names
	for k in _legacy_global_var_names:
		globals().pop(k, None)

# Initialization of legacy globals.  No functions/classes below this point
# please!  When the above functions and classes become independent of the
# below global variables, it will be possible to make the below code
# conditional on a backward compatibility flag (backward compatibility could
# be disabled via an environment variable, for example).  This will enable new
# code that is aware of this flag to import portage without the unnecessary
# overhead (and other issues!) of initializing the legacy globals.

def init_legacy_globals():
	global _globals_initialized
	if _globals_initialized:
		return
	_globals_initialized = True

	global db, settings, root, portdb, selinux_enabled, mtimedbfile, mtimedb, \
	archlist, features, groups, pkglines, thirdpartymirrors, usedefaults, \
	profiledir, flushmtimedb

	# Portage needs to ensure a sane umask for the files it creates.
	os.umask(0o22)

	kwargs = {}
	for k, envvar in (("config_root", "PORTAGE_CONFIGROOT"), ("target_root", "ROOT")):
		kwargs[k] = os.environ.get(envvar, "/")

	global _initializing_globals
	_initializing_globals = True
	db = create_trees(**kwargs)
	del _initializing_globals

	settings = db["/"]["vartree"].settings

	for myroot in db:
		if myroot != "/":
			settings = db[myroot]["vartree"].settings
			break

	root = settings["ROOT"]
	output._init(config_root=settings['PORTAGE_CONFIGROOT'])

	# ========================================================================
	# COMPATIBILITY
	# These attributes should not be used
	# within Portage under any circumstances.
	# ========================================================================
	archlist    = settings.archlist()
	features    = settings.features
	groups      = settings["ACCEPT_KEYWORDS"].split()
	pkglines    = settings.packages
	selinux_enabled   = settings.selinux_enabled()
	thirdpartymirrors = settings.thirdpartymirrors()
	usedefaults       = settings.use_defs
	profiledir  = os.path.join(settings["PORTAGE_CONFIGROOT"], PROFILE_PATH)
	if not os.path.isdir(profiledir):
		profiledir = None
	def flushmtimedb(record):
		writemsg("portage.flushmtimedb() is DEPRECATED\n")
	# ========================================================================
	# COMPATIBILITY
	# These attributes should not be used
	# within Portage under any circumstances.
	# ========================================================================

if True:

	_mtimedb_initialized = False
	mtimedb     = _MtimedbProxy("mtimedb")
	mtimedbfile = _MtimedbProxy("mtimedbfile")

	_portdb_initialized  = False
	portdb = _PortdbProxy()

	_globals_initialized = False

	for k in ("db", "settings", "root", "selinux_enabled",
		"archlist", "features", "groups",
		"pkglines", "thirdpartymirrors", "usedefaults", "profiledir",
		"flushmtimedb"):
		globals()[k] = _LegacyGlobalProxy(k)

# Clear the cache
dircache={}

# ============================================================================
# ============================================================================

