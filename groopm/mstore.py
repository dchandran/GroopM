#!/usr/bin/env python
###############################################################################
#                                                                             #
#    mstore.py                                                                #
#                                                                             #
#    GroopM - Low level data management and file parsing                      #
#                                                                             #
#    Copyright (C) Michael Imelfort                                           #
#                                                                             #
###############################################################################
#                                                                             #
#          .d8888b.                                    888b     d888          #
#         d88P  Y88b                                   8888b   d8888          #
#         888    888                                   88888b.d88888          #
#         888        888d888 .d88b.   .d88b.  88888b.  888Y88888P888          #
#         888  88888 888P"  d88""88b d88""88b 888 "88b 888 Y888P 888          #
#         888    888 888    888  888 888  888 888  888 888  Y8P  888          #
#         Y88b  d88P 888    Y88..88P Y88..88P 888 d88P 888   "   888          #
#          "Y8888P88 888     "Y88P"   "Y88P"  88888P"  888       888          #
#                                             888                             #
#                                             888                             #
#                                             888                             #
#                                                                             #
###############################################################################
#                                                                             #
#    This program is free software: you can redistribute it and/or modify     #
#    it under the terms of the GNU General Public License as published by     #
#    the Free Software Foundation, either version 3 of the License, or        #
#    (at your option) any later version.                                      #
#                                                                             #
#    This program is distributed in the hope that it will be useful,          #
#    but WITHOUT ANY WARRANTY; without even the implied warranty of           #
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            #
#    GNU General Public License for more details.                             #
#                                                                             #
#    You should have received a copy of the GNU General Public License        #
#    along with this program. If not, see <http://www.gnu.org/licenses/>.     #
#                                                                             #
###############################################################################

__author__ = "Michael Imelfort"
__copyright__ = "Copyright 2012"
__credits__ = ["Michael Imelfort"]
__license__ = "GPL3"
__version__ = "0.3.0"
__maintainer__ = "Michael Imelfort"
__email__ = "mike@mikeimelfort.com"
__status__ = "Alpha"
__current_GMDB_version__ = 1

###############################################################################

from sys import exc_info, exit
from os.path import splitext as op_splitext, basename as op_basename
from string import maketrans as s_maketrans

import tables
import numpy as np
import pysam

# GroopM imports
import groopmExceptions as ge
import groopmTimekeeper as gtime
from PCA import PCA, Center

np.seterr(all='raise')     

###############################################################################
###############################################################################
###############################################################################
###############################################################################
class GMDataManager:
    """Top level class for manipulating GroopM data
    
    Use this class for parsing in raw data into a hdf DB and 
    for reading from and updating same DB

    NOTE: All tables are kept in the same order indexed by the contig ID
    Tables managed by this class are listed below

    ------------------------
     PROFILES
    group = '/profile'
    ------------------------
    **Kmer Signature**
    table = 'kms'
    'mer1' : tables.FloatCol(pos=0)
    'mer2' : tables.FloatCol(pos=1)
    'mer3' : tables.FloatCol(pos=2)
    ...
    
    **Kmer Vals**
    table = 'kpca'
    'pc1' : tables.FloatCol(pos=0)
    'pc2' : tables.FloatCol(pos=1)
    
    **Coverage profile**
    table = 'coverage'
    'stoit1' : tables.FloatCol(pos=0)
    'stoit2' : tables.FloatCol(pos=1)
    'stoit3' : tables.FloatCol(pos=2)
    ...

    ------------------------
     LINKS
    group = '/links'
    ------------------------
    ** Links **
    table = 'links'
    'contig1'    : tables.Int32Col(pos=0)            # reference to index in meta/contigs
    'contig2'    : tables.Int32Col(pos=1)            # reference to index in meta/contigs
    'numReads'   : tables.Int32Col(pos=2)            # number of reads supporting this link 
    'linkType'   : tables.Int32Col(pos=3)            # the type of the link (SS, SE, ES, EE)
    'gap'        : tables.Int32Col(pos=4)            # the estimated gap between the contigs
    
    ------------------------
     METADATA
    group = '/meta'
    ------------------------
    ** Metadata **
    table = 'meta'
    'stoitColNames' : tables.StringCol(512, pos=0)
    'numStoits'     : tables.Int32Col(pos=1)
    'merColNames'   : tables.StringCol(4096,pos=2)
    'merSize'       : tables.Int32Col(pos=3)
    'numMers'       : tables.Int32Col(pos=4)
    'numCons'       : tables.Int32Col(pos=5)
    'numBins'       : tables.Int32Col(pos=6)
    'clustered'     : tables.BoolCol(pos=7)           # set to true after clustering is complete
    'complete'      : tables.BoolCol(pos=8)           # set to true after clustering finishing is complete
    'formatVersion' : tables.Int32Col(pos=9)       # groopm file version

    ** Contigs **
    table = 'contigs'
    'cid'    : tables.StringCol(512, pos=0)
    'bid'    : tables.Int32Col(pos=1)
    'length' : tables.Int32Col(pos=2)
    
    ** Bins **
    table = 'bin'
    'bid'        : tables.Int32Col(pos=0)
    'numMembers' : tables.Int32Col(pos=1)

    """
    def __init__(self): pass

#------------------------------------------------------------------------------
# DB CREATION / INITIALISATION  - PROFILES

    def createDB(self, bamFiles, contigs, dbFileName, timer, kmerSize=4, dumpAll=False, force=False):
        """Main wrapper for parsing all input files"""
        # load all the passed vars
        dbFileName = dbFileName
        contigsFile = contigs
        stoitColNames = []
        
        kse = KmerSigEngine(kmerSize)
        conParser = ContigParser()
        bamParser = BamParser()

        cid_2_indices = {}
        
        # make sure we're only overwriting existing DBs with the users consent
        try:
            with open(dbFileName) as f:
                if(not force):
                    user_option = self.promptOnOverwrite(dbFileName)
                    if(user_option != "Y"):
                        print "Operation cancelled"
                        return False
                    else:
                        print "Overwriting database",dbFileName
        except IOError as e:
            print "Creating new database", dbFileName
        
        # create the db
        try:        
            with tables.openFile(dbFileName, mode = "w", title = "GroopM") as h5file:
                # Create groups under "/" (root) for storing profile information and metadata
                profile_group = h5file.createGroup("/", 'profile', 'Assembly profiles')
                meta_group = h5file.createGroup("/", 'meta', 'Associated metadata')
                links_group = h5file.createGroup("/", 'links', 'Paired read link information')
                #------------------------
                # parse contigs and make kmer sigs
                #
                # Contig IDs are key. Any keys existing in other files but not in this file will be
                # ignored. Any missing keys in other files will be given the default profile value 
                # (typically 0). Ironically, we don't store the CIDs here, these are saved one time
                # only in the bin table 
                #------------------------
                try:
                    with open(contigsFile, "r") as f:
                        try:
                            (con_names, con_lengths, con_ksigs) = conParser.parse(f, kse)
                            num_cons = len(con_names)
                            cid_2_indices = dict(zip(con_names, range(num_cons)))
                        except:
                            print "Error parsing contigs"
                            raise
                except:
                    print "Could not parse contig file:",contigsFile,exc_info()[0]
                    raise

                # store the raw calculated kmer sigs in one table
                db_desc = []
                for mer in kse.kmerCols:
                     db_desc.append((mer, float))
                try:
                    h5file.createTable(profile_group,
                                       'kms',
                                       np.array(con_ksigs, dtype=db_desc),
                                       title='Kmer signatures',
                                       expectedrows=num_cons
                                       )
                except:
                    print "Error creating KMERSIG table:", exc_info()[0]
                    raise
                
                # compute the PCA of the ksigs and store these too
                pc_ksigs = conParser.PCAKSigs(con_ksigs)
                
                db_desc = [('pc1', float),
                           ('pc2', float)]
                try:
                    h5file.createTable(profile_group,
                                       'kpca',
                                       np.array(pc_ksigs, dtype=db_desc),
                                       title='Kmer signature PCAs',
                                       expectedrows=num_cons
                                       )
                except:
                    print "Error creating KMERVALS table:", exc_info()[0]
                    raise
                               
                #------------------------
                # Add a table for the contigs
                #------------------------
                self.setBinAssignments((h5file, meta_group), 
                                       image=zip(con_names,
                                                 [0]*num_cons,
                                                 con_lengths)
                                       )

                #------------------------
                # Add a table for the bins
                #------------------------
                self.setBinStats(dbFileName, [], firstWrite=True)
                
                print "    %s" % timer.getTimeStamp()

                #------------------------
                # parse bam files
                #------------------------
                # build a table template based on the number of bamfiles we have
                db_desc = []
                for bf in bamFiles:
                    # assume the file is called something like "fred.bam"
                    # we want to rip off the ".bam" part
                    bam_desc = getBamDescriptor(bf)
                    db_desc.append((bam_desc, float))
                    stoitColNames.append(bam_desc)
                    
                (rowwise_links, cov_profiles) = bamParser.parse(bamFiles,
                                                                con_names,
                                                                cid_2_indices)
                try:
                    h5file.createTable(profile_group,
                                       'coverage',
                                       np.array(cov_profiles, dtype=db_desc),
                                       title="Bam based coverage",
                                       expectedrows=num_cons)
                except:
                    print "Error creating coverage table:", exc_info()[0]
                    raise

                #------------------------
                # contig links
                #------------------------
                # set table size according to the number of links returned from
                # the previous call
                db_desc = [('contig1', int),
                           ('contig2', int),
                           ('numReads', int),
                           ('linkType', int),
                           ('gap', int)]
                try:
                    h5file.createTable(links_group,
                                       'links',
                                       np.array(rowwise_links, dtype=db_desc),
                                       title="ContigLinks",
                                       expectedrows=len(rowwise_links))
                except:
                    print "Error creating links table:", exc_info()[0]
                    raise
                print "    %s" % timer.getTimeStamp()
                
                #------------------------
                # Add metadata
                #------------------------
                meta_data = (str.join(',',stoitColNames),
                             len(stoitColNames.split(',')),
                             str.join(',',kse.kmerCols),
                             kmerSize,
                             len(kse.kmerCols),
                             num_cons,
                             0,
                             False,
                             False,
                             __current_GMDB_version__)
                self.setMeta(h5file, meta_data)
                
        except:
            print "Error creating database:", dbFileName, exc_info()[0]
            raise
        
        print "****************************************************************"
        print "Data loaded successfully!"
        print " ->",num_cons,"contigs"
        print " ->",len(stoitColNames.split(',')),"BAM files"
        print "Written to: '"+dbFileName+"'"
        print "****************************************************************"
        print "    %s" % timer.getTimeStamp()

        if(dumpAll):
            self.dumpAll(dbFileName)
            
        # all good!
        return True

    def promptOnOverwrite(self, dbFileName, minimal=False):
        """Check that the user is ok with overwriting the db"""
        input_not_ok = True
        valid_responses = ['Y','N']
        vrs = ",".join([str.lower(str(x)) for x in valid_responses])
        while(input_not_ok):
            if(minimal):
                option = raw_input(" Overwrite? ("+vrs+") : ")
            else: 
                
                option = raw_input(" ****WARNING**** Database: '"+dbFileName+"' exists.\n" \
                                   " If you continue you *WILL* delete any previous analyses!\n" \
                                   " Overwrite? ("+vrs+") : ")
            if(option.upper() in valid_responses):
                print "****************************************************************"
                return option.upper()
            else:
                print "Error, unrecognised choice '"+option.upper()+"'"
                minimal = True

#------------------------------------------------------------------------------
# DB UPGRADE 

    def checkAndUpgradeDB(self, dbFileName, silent=False):
        """Check the DB and upgrade if necessary"""
        # get the DB format version
        this_DB_version = self.getGMFormat(dbFileName)
        if __current_GMDB_version__ == this_DB_version:
            if not silent:
                print "    GroopM DB version up to date"
            return 
        
        # now, if we get here then we need to do some work
        upgrade_tasks = {}
        upgrade_tasks[(0,1)] = self.upgrageDB_0_to_1 

        # we need to apply upgrades in order!
        # keep applying the upgrades as long as we need to        
        while this_DB_version < __current_GMDB_version__:
            task = (this_DB_version, this_DB_version+1)
            upgrade_tasks[task](dbFileName)
            this_DB_version += 1 
        
    def upgrageDB_0_to_1(self, dbFileName):
        """Upgrade a GM db from version 0 to version 1"""
        print "*******************************************************************************\n"
        print "              *** Upgrading GM DB from version 0 to version 1 ***" 
        print ""
        print "                            please be patient..."
        print ""    
        # the change in this version is that we'll be saving the first 
        # two kmerSig PCA's in a separate table
        print "    Calculating and storing the kmerSig PCAs"

        # compute the PCA of the ksigs
        pc_ksigs = self.getKmerSigs(dbFileName)

        db_desc = [('pc1', float),
                   ('pc2', float)]
        try:
            with tables.openFile(dbFileName, mode='a', rootUEP="/profile") as profile_group:
                try:
                    profile_group.createTable('/',
                                              'kpca',
                                              np.array(pc_ksigs, dtype=db_desc),
                                              title='Kmer signature PCAs',
                                              expectedrows=num_cons
                                              )
                except:
                    print "Error creating KMERVALS table:", exc_info()[0]
                    raise
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise
        
        # update the formatVersion field and we're done
        self.setGMDBFormat(dbFileName, 1)
        print "*******************************************************************************"

#------------------------------------------------------------------------------
# GET LINKS 

    def restoreLinks(self, dbFileName, indices=[], silent=False):
        """Restore the links hash for a given set of indicies"""
        full_record = []
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                full_record = [list(x) for x in h5file.root.links.links.readWhere("contig1 >= 0")]
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise
        
        if indices == []:
            # get all!
            indices = self.getConditionalIndices(dbFileName, silent=silent)
        
        links_hash = {}
        if full_record != []:
            for record in full_record:
                # make sure we have storage
                if record[0] in indices and record[1] in indices:
                    try:
                        links_hash[record[0]].append(record[1:])
                    except KeyError:
                        links_hash[record[0]] = [record[1:]]
        return links_hash
    
#------------------------------------------------------------------------------
# GET / SET DATA TABLES - PROFILES 

    def getConditionalIndices(self, dbFileName, condition='', silent=False):
        """return the indices into the db which meet the condition"""
        # check the DB out and see if we need to change anything about it
        self.checkAndUpgradeDB(dbFileName, silent=silent)

        if('' == condition):
            condition = "cid != ''" # no condition breaks everything!
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                return np.array([x.nrow for x in h5file.root.meta.contigs.where(condition)])
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise

    def getCoverageProfiles(self, dbFileName, condition='', indices=np.array([])):
        """Load coverage profiles"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                if(np.size(indices) != 0):
                    return np.array([list(h5file.root.profile.coverage[x]) for x in indices])
                else:
                    if('' == condition):
                        condition = "cid != ''" # no condition breaks everything!
                    return np.array([list(h5file.root.profile.coverage[x.nrow]) for x in h5file.root.meta.contigs.where(condition)])
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise

    def nukeBins(self, dbFileName):
        """Reset all bin information, completely"""
        print "    Clearing all old bin information from",dbFileName
        self.setBinStats(dbFileName, [])
        self.setNumBins(dbFileName, 0)
        self.setBinAssignments(dbFileName, updates={}, nuke=True)

    def setBinStats(self, dbFileName, updates, firstWrite=False):
        """Set bins table 
        
        updates is a list of tuples which looks like:
        [ (bid, numMembers) ]
        """
        db_desc = [('bid', int),
                   ('numMembers', int)]
        bd = np.array(updates, dtype=db_desc)

        try:
            with tables.openFile(dbFileName, mode='a', rootUEP="/") as h5file:
                mg = h5file.getNode('/', name='meta')
                if not firstWrite:
                    t_name = 'tmp_bin'
                    # nuke any previous failed attempts
                    try:
                        h5file.removeNode(mg, 'tmp_bin')
                    except:
                        pass
                else:
                    t_name = 'bin'
                
                try:
                    h5file.createTable(mg,
                                       t_name,
                                       bd,
                                       title="Bin information",
                                       expectedrows=1)
                except:
                    print "Error creating META table:", exc_info()[0]
                    raise
                
                if not firstWrite:
                    # rename the tmp table to overwrite
                    h5file.renameNode(mg, 'bin', 'tmp_bin', overwrite=True)
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise

    def getBinStats(self, dbFileName):
        """Load data from bins table
        
        Returns a dict of type:
        { bid : numMembers }
        """
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                ret_dict = {}
                all_rows = h5file.root.meta.bin.read()
                for row in all_rows:
                    ret_dict[row[0]] = row[1]
                return ret_dict
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise
        return {}
                
    def getBins(self, dbFileName, condition='', indices=np.array([])):
        """Load per-contig bins"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                if(np.size(indices) != 0):
                    return np.array([h5file.root.meta.contigs[x][1] for x in indices]).ravel()
                else:
                    if('' == condition):
                        condition = "cid != ''" # no condition breaks everything!
                    return np.array([list(x)[1] for x in h5file.root.meta.contigs.readWhere(condition)]).ravel()
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise

    def setBinAssignments(self, storage, updates=None, image=None, nuke=False):
        """Set per-contig bins
        
        updates is a dictionary which looks like:
        { tableRow : binValue }
        if updates is set then storage is the
        path to the hdf file
        
        image is a list of tuples which look like:
        [(cid, bid, len)]
        if image is set then storage is a tuple of type:
        (h5file, group)
        """
        db_desc = [('cid', '|S512'),
                   ('bid', int),
                   ('length', int)]
        closeh5 = False
        if updates is not None:
            # we need to build the image
            dbFileName = storage
            contig_names = self.getContigNames(dbFileName)
            contig_lengths = self.getContigLengths(dbFileName)
            num_cons = len(contig_lengths)
            if nuke:
                # clear all bin assignments
                bins = [0]*num_cons
            else:
                bins = self.getBins(dbFileName)
            
            # now apply the updates
            for tr in updates.keys():
                bins[tr] = updates[tr] 
            
            # and build the image
            image = np.array(zip(contig_names, bins, contig_lengths),
                             dtype=db_desc)
            
            try:
                h5file = tables.openFile(dbFileName, mode='a')
            except:
                print "Error opening DB:",dbFileName, exc_info()[0]
                raise                
            meta_group = h5file.getNode('/', name='meta')
            closeh5 = True
            
        elif image is not None:
            h5file = storage[0]
            meta_group = storage[1]
            num_cons = len(image)
            image = np.array(image,
                             dtype=db_desc)
        else:
            print "get with the program dude"
            return
        
        # now we write the data
        try:
            # get rid of any failed attempts
            h5file.removeNode(meta_group, 'tmp_contigs')
        except:
            pass
        
        try:
            h5file.createTable(meta_group,
                               'tmp_contigs',
                               image,
                               title="Contig information",
                               expectedrows=num_cons)
        except:
            print "Error creating CONTIG table:", exc_info()[0]
            raise
        
        # rename the tmp table to overwrite
        h5file.renameNode(meta_group, 'contigs', 'tmp_contigs', overwrite=True)  
        if closeh5:
            h5file.close()
        
    def getContigNames(self, dbFileName, condition='', indices=np.array([])):
        """Load contig names"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                if(np.size(indices) != 0):
                    return np.array([h5file.root.meta.contigs[x][0] for x in indices]).ravel()
                else:
                    if('' == condition):
                        condition = "cid != ''" # no condition breaks everything!
                    return np.array([list(x)[0] for x in h5file.root.meta.contigs.readWhere(condition)]).ravel()
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise

    def getContigLengths(self, dbFileName, condition='', indices=np.array([])):
        """Load contig lengths"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                if(np.size(indices) != 0):
                    return np.array([h5file.root.meta.contigs[x][2] for x in indices]).ravel()
                else:
                    if('' == condition):
                        condition = "cid != ''" # no condition breaks everything!
                    return np.array([list(x)[2] for x in h5file.root.meta.contigs.readWhere(condition)]).ravel()
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise

    def getKmerSigs(self, dbFileName, condition='', indices=np.array([])):
        """Load kmer sigs"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                if(np.size(indices) != 0):
                    return np.array([list(h5file.root.profile.kms[x]) for x in indices])
                else:
                    if('' == condition):
                        condition = "cid != ''" # no condition breaks everything!
                    return np.array([list(h5file.root.profile.kms[x.nrow]) for x in h5file.root.meta.contigs.where(condition)])
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise

    def getKmerPCAs(self, dbFileName, condition='', indices=np.array([])):
        """Load kmer sig PCAs"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                if(np.size(indices) != 0):
                    return np.array([list(h5file.root.profile.kpca[x]) for x in indices])
                else:
                    if('' == condition):
                        condition = "cid != ''" # no condition breaks everything!
                    return np.array([list(h5file.root.profile.kpca[x.nrow]) for x in h5file.root.meta.contigs.where(condition)])
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise

#------------------------------------------------------------------------------
# GET / SET METADATA 

    def setMeta(self, h5file, metaData, overwrite=False):
        """Write metadata into the table
        
        metaData should be a tuple of values
        """
        db_desc = [('stoitColNames', '|S512'),
                   ('numStoits', int),
                   ('merColNames', '|S4096'),
                   ('merSize', int),
                   ('numMers', int),
                   ('numCons', int),
                   ('numBins', int),
                   ('clustered', bool),     # set to true after clustering is complete
                   ('complete', bool),      # set to true after clustering finishing is complete
                   ('formatVersion', int)]
        md = np.array([metaData], dtype=db_desc)
        
        # get hold of the group
        mg = h5file.getNode('/', name='meta')
        
        if overwrite:
            t_name = 'tmp_meta'
            # nuke any previous failed attempts
            try:
                h5file.removeNode(mg, 'tmp_meta')
            except:
                pass
        else:
            t_name = 'meta'
        
        try:
            h5file.createTable(mg,
                               t_name,
                               md,
                               "Descriptive data",
                               expectedrows=1)
        except:
            print "Error creating META table:", exc_info()[0]
            raise
        
        if overwrite:
            # rename the tmp table to overwrite
            h5file.renameNode(mg, 'meta', 'tmp_meta', overwrite=True)

    def getMetaField(self, dbFileName, fieldName):
        """return the value of fieldName in the metadata tables"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                # theres only one value
                return h5file.root.meta.meta.read()[fieldName][0]
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise

    def setGMDBFormat(self, dbFileName, version):
        """Update the GMDB format version"""
        stoit_col_names = self.getStoitColNames(dbFileName)
        meta_data = (stoit_col_names,
                    len(stoit_col_names.split(',')),
                    self.getMerColNames(dbFileName),
                    self.getMerSize(dbFileName),
                    self.getNumMers(dbFileName),
                    self.getNumCons(dbFileName),
                    self.getNumBins(dbFileName),
                    self.isClustered(dbFileName),
                    self.isComplete(dbFileName),
                    version)
        try:
            with tables.openFile(dbFileName, mode='a', rootUEP="/") as h5file:
                self.setMeta(h5file, meta_data, overwrite=True)
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise

    def getGMFormat(self, dbFileName):
        """return the format version of this GM file"""
        # this guy needs to be a bit different to the other meta methods
        # becuase earlier versions of GM didn't include a format parameter
        with tables.openFile(dbFileName, mode='r') as h5file:
            # theres only one value
            try:
                this_DB_version = h5file.root.meta.meta.read()['formatVersion'][0]
            except ValueError:
                # this happens when an oldskool formatless DB is loaded
                this_DB_version = 0
        return this_DB_version

    def getNumStoits(self, dbFileName):
        """return the value of numStoits in the metadata tables"""
        return self.getMetaField(dbFileName, 'numStoits')
            
    def getMerColNames(self, dbFileName):
        """return the value of merColNames in the metadata tables"""
        return self.getMetaField(dbFileName, 'merColNames')
            
    def getMerSize(self, dbFileName):
        """return the value of merSize in the metadata tables"""
        return self.getMetaField(dbFileName, 'merSize')

    def getNumMers(self, dbFileName):
        """return the value of numMers in the metadata tables"""
        return self.getMetaField(dbFileName, 'numMers')

    def getNumCons(self, dbFileName):
        """return the value of numCons in the metadata tables"""
        return self.getMetaField(dbFileName, 'numCons')

    def setNumBins(self, dbFileName, numBins):
        """set the number of bins"""
        stoit_col_names = self.getStoitColNames(dbFileName)
        meta_data = (stoit_col_names,
                    len(stoit_col_names.split(',')),
                    self.getMerColNames(dbFileName),
                    self.getMerSize(dbFileName),
                    self.getNumMers(dbFileName),
                    self.getNumCons(dbFileName),
                    numBins,
                    self.isClustered(dbFileName),
                    self.isComplete(dbFileName),
                    self.getGMFormat(dbFileName))
        try:
            with tables.openFile(dbFileName, mode='a', rootUEP="/") as h5file:
                self.setMeta(h5file, meta_data, overwrite=True)
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise

    def getNumBins(self, dbFileName):
        """return the value of numBins in the metadata tables"""
        return self.getMetaField(dbFileName, 'numBins')
        
    def getStoitColNames(self, dbFileName):
        """return the value of stoitColNames in the metadata tables"""
        return self.getMetaField(dbFileName, 'stoitColNames')

#------------------------------------------------------------------------------
# GET / SET WORKFLOW FLAGS 

    def isClustered(self, dbFileName):
        """Has this data set been clustered?"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                return h5file.root.meta.meta.read()['clustered']
        except:
            print "Error opening database:", dbFileName, exc_info()[0]
            raise
            
    def setClustered(self, dbFileName, state):
        """Set the state of clustering"""
        stoit_col_names = self.getStoitColNames(dbFileName)
        meta_data = (stoit_col_names,
                    len(stoit_col_names.split(',')),
                    self.getMerColNames(dbFileName),
                    self.getMerSize(dbFileName),
                    self.getNumMers(dbFileName),
                    self.getNumCons(dbFileName),
                    self.getNumBins(dbFileName),
                    state,
                    self.isComplete(dbFileName),
                    self.getGMFormat(dbFileName))
        try:
            with tables.openFile(dbFileName, mode='a', rootUEP="/") as h5file:
                self.setMeta(h5file, meta_data, overwrite=True)
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise
            
    def isComplete(self, dbFileName):
        """Has this data set been *completely* clustered?"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                return h5file.root.meta.meta.read()['complete']
        except:
            print "Error opening database:", dbFileName, exc_info()[0]
            raise

    def setComplete(self, dbFileName, state):
        """Set the state of completion"""
        stoit_col_names = self.getStoitColNames(dbFileName)
        meta_data = (stoit_col_names,
                    len(stoit_col_names.split(',')),
                    self.getMerColNames(dbFileName),
                    self.getMerSize(dbFileName),
                    self.getNumMers(dbFileName),
                    self.getNumCons(dbFileName),
                    self.getNumBins(dbFileName),
                    self.isClustered(dbFileName),
                    state,
                    self.getGMFormat(dbFileName))
        try:
            with tables.openFile(dbFileName, mode='a', rootUEP="/") as h5file:
                self.setMeta(h5file, meta_data, overwrite=True)
        except:
            print "Error opening DB:",dbFileName, exc_info()[0]
            raise

#------------------------------------------------------------------------------
# FILE / IO 

    def dumpContigs(self, table):
        """Raw dump of contig information"""
        print "-----------------------------------"
        print "Contigs table"
        print "-----------------------------------"
        for row in table:
            print row['cid'],",",row['length'],",",row['bid']

    def dumpbins(self, table):
        """Raw dump of bin information"""
        print "-----------------------------------"
        print "Bins table"
        print "-----------------------------------"

    def dumpMeta(self, table):
        """Raw dump of metadata"""
        print "-----------------------------------"
        print "MetaData table"
        print "-----------------------------------"
        for row in table:
            print row['stoitColNames']
            print row['merColNames']
            print row['merSize']
            print row['numMers']
            print row['numCons']
            print row['numBins']
            print row['clustered']
            print row['complete']

    def dumpAll(self, dbFileName):
        """Dump all contents of all DBs to screen"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                
                # get the metadata
                META_row = h5file.root.meta.meta.read()
                print META_row['stoitColNames']
    
                stoitColNames = META_row['stoitColNames'][0].split(",")
                merSize = META_row['merSize']
     
                kse = KmerSigEngine(merSize)
                conParser = ContigParser()
                bamParser = BamParser()
    
                bamParser.dumpCovTable(h5file.root.profile.coverage, stoitColNames)
                conParser.dumpTnTable(h5file.root.profile.kms, kse.kmerCols)
                self.dumpContigs(h5file.root.meta.contigs)
                self.dumpMeta(h5file.root.meta.meta)
        except:
            print "Error opening database:", dbFileName, exc_info()[0]
            raise

###############################################################################
###############################################################################
###############################################################################
###############################################################################
class ContigParser:
    """Main class for reading in and parsing contigs"""
    def __init__(self): pass

    def readfq(self, fp): # this is a generator function
        """https://github.com/lh3"""
        last = None # this is a buffer keeping the last unprocessed line
        while True: # mimic closure; is it a bad idea?
            if not last: # the first record or a record following a fastq
                for l in fp: # search for the start of the next record
                    if l[0] in '>@': # fasta/q header line
                        last = l[:-1] # save this line
                        break
            if not last: break
            name, seqs, last = last[1:].split()[0], [], None
            for l in fp: # read the sequence
                if l[0] in '@+>':
                    last = l[:-1]
                    break
                seqs.append(l[:-1])
            if not last or last[0] != '+': # this is a fasta record
                yield name, ''.join(seqs), None # yield a fasta record
                if not last: break
            else: # this is a fastq record
                seq, leng, seqs = ''.join(seqs), 0, []
                for l in fp: # read the quality
                    seqs.append(l[:-1])
                    leng += len(l) - 1
                    if leng >= len(seq): # have read enough quality
                        last = None
                        yield name, seq, ''.join(seqs); # yield a fastq record
                        break
                if last: # reach EOF before reading enough quality
                    yield name, seq, None # yield a fasta record instead
                    break
                
    def parse(self, contigFile, kse):
        """Do the heavy lifting of parsing"""
        print "Parsing contigs"        
        contigInfo = {} # save everything here first so we can sort accordingly
        for cid,seq,qual in self.readfq(contigFile):
            contigInfo[cid] = (kse.getKSig(seq.upper()), len(seq))

        # sort the contig names here once!
        con_names = np.array(sorted(contigInfo.keys()))
        # keep everything in order...
        con_lengths = np.array([contigInfo[cid][1] for cid in con_names])
        con_ksigs = [contigInfo[cid][0] for cid in con_names]
        return (con_names, con_lengths, con_ksigs)
        
        # store the PCA'd kmersigs
        k_PCA_data = np.reshape(k_PCA_data, (rows,cols))
        self.storeSigPCAs(k_PCA_data, kPCATable)
        
    def PCAKSigs(self, kSigs):
        """PCA kmer sig data
        
        returns an array of tuples [(pc1, pc2), (pc1, pc2), ...]
        """
        # make a copy
        data = np.copy(kSigs)
        Center(data,verbose=0)
        p = PCA(data)
        components = p.pc()
        
        # only need the first two PCs
        PCAs = components[:,0:2]

        # normalise to fit between 0 and 1
        min  = np.min(PCAs, axis=0)
        PCAs -= min
        max  = np.max(PCAs, axis=0)
        PCAs /= max
        
        return [tuple(i) for i in PCAs]

    def getWantedSeqs(self, contigFile, wanted, storage={}):
        """Do the heavy lifting of parsing"""
        print "Parsing contigs"        
        for cid,seq,qual in self.readfq(contigFile):
            if(cid in wanted):
                storage[cid] = seq
        return storage 

    def dumpTnTable(self, table, kmerCols):
        """Dump the guts of the TN table"""
        print "-----------------------------------"
        print "KmerSig table"
        print "-----------------------------------"
        for row in table:
            for mer in kmerCols:
                print ",",row[mer],
            print ""

###############################################################################
###############################################################################
###############################################################################
###############################################################################
class KmerSigEngine:
    """Simple class for determining kmer signatures"""
    def __init__(self, kLen=4):
        self.kLen = kLen
        self.compl = s_maketrans('ACGT', 'TGCA')
        (self.kmerCols, self.llDict) = self.makeKmerColNames(makeLL=True)
        self.numMers = len(self.kmerCols)
        
    def makeKmerColNames(self, makeLL=False):
        """Work out the range of kmers required based on kmer length
        
        returns a list of sorted kmers and optionally a llo dict
        """
        # build up the big list
        base_words = ("A","C","G","T")
        out_list = ["A","C","G","T"]
        for i in range(1,self.kLen):
            working_list = []
            for mer in out_list:
                for char in base_words:
                    working_list.append(mer+char)
            out_list = working_list
        
        # pare it down based on lexicographical ordering
        ret_list = []
        ll_dict = {}
        for mer in out_list:
            lmer = self.shiftLowLexi(mer)
            ll_dict[mer] = lmer 
            if lmer not in ret_list:
                ret_list.append(lmer)
        if makeLL:
            return (sorted(ret_list), ll_dict)
        else:
            return sorted(ret_list)

    def getGC(self, seq):
        """Get the GC of a sequence"""
        Ns = seq.count('N') + seq.count('n')
        compl = s_maketrans('ACGTacgtnN', '0110011000')
        return sum([float(x) for x in list(seq.translate(compl))])/float(len(seq) - Ns)

    def shiftLowLexi(self, seq):
        """Return the lexicographically lowest form of this sequence"""
        rseq = self.revComp(seq)
        if(seq < rseq):
            return seq
        return rseq

    def shiftLowLexiMer(self, seq):
        """Return the lexicographically lowest form of this kmer"""
        try:
            return self.llDict[seq]
        except KeyError:
            return seq
        
    def revComp(self, seq):
        """Return the reverse complement of a sequence"""
        # build a dictionary to know what letter to switch to
        return seq.translate(self.compl)[::-1]
    
    def getKSig(self, seq):
        """Work out kmer signature for a nucleotide sequence
        
        returns a tuple of floats which is the kmer sig
        """
        # tmp storage
        sig = dict(zip(self.kmerCols, [0.0] * self.numMers))
        # the number fo kmers in this sequence
        num_mers = len(seq)-self.kLen+1
        for i in range(0,num_mers):
            try:
                this_mer = self.llDict[seq[i:i+self.kLen]]
                try:
                    sig[this_mer] += 1.0
                except KeyError:
                    # Ns
                    sig[this_mer] = 1.0
            except KeyError:
                # typically due to an N in the sequence...
                pass

        # normalise by length and return
        return tuple([sig[x] / num_mers for x in self.kmerCols])

###############################################################################
###############################################################################
###############################################################################
###############################################################################
class BamParser:
    """Parse multiple bam files and write the output to hdf5 """

    def __init__(self): pass
    
    def parse(self, bamFiles, contigNames, cid2Indices):
        """Parse multiple bam files and store the results in the main DB
        
        table: a table in an open h5 file like "CID,COV_1,...,COV_n,length"
        stoitColNames: names of the COV_x columns
        """
        print "Importing BAM files"
        from bamtyper.utilities import BamParser as BTBP
        BP = BTBP()
        (links, ref_lengths, coverages) = BP.getLinks(bamFiles, full=False, verbose=True, doCoverage=True, minJoin=5)

        # go through all the contigs sorted by name.
        # we want to make an array of tuples of coverage sigs
        cov_sigs = []
        bam_range = range(len(bamFiles))
        for cid in contigNames:
            tmp_cov = []
            for i in bam_range:
                try:
                    tmp_cov.append(coverages[i][cid])
                except KeyError:
                    # may be no coverage for this contig
                    tmp_cov.append(0.0)
            cov_sigs.append(tuple(tmp_cov))
        
        # transform the links into something a little easier to parse later
        rowwise_links = []
        for cid in links:
            for link in links[cid]:
                try:
                    rowwise_links.append((cid2Indices[cid],          # contig 1 
                                          cid2Indices[link[0]],      # contig 2
                                          int(link[1]),               # numReads
                                          int(link[2]),               # linkType
                                          int(link[3])                # gap
                                          ))
                except KeyError:
                    pass
        return (rowwise_links, cov_sigs)
    
    def dumpCovTable(self, table, stoitColNames):
        """Dump the guts of the coverage table"""
        print "-----------------------------------"
        print "Coverage table"
        print "-----------------------------------"
        for row in table:
            for colName in stoitColNames:
                print ",",row[colName],
            print ""

def getBamDescriptor(fullPath):
    """AUX: Reduce a full path to just the file name minus extension"""
    return op_splitext(op_basename(fullPath))[0]

###############################################################################
###############################################################################
###############################################################################
###############################################################################
