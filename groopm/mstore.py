#!/usr/bin/env python
###############################################################################
#                                                                             #
#    mstore.py                                                                #
#                                                                             #
#    GroopM data management                                                   #
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
__version__ = "0.0.1"
__maintainer__ = "Michael Imelfort"
__email__ = "mike@mikeimelfort.com"
__status__ = "Development"

###############################################################################
import sys
import os
import tables

import pysam
import string
import re

import colorsys
import matplotlib as mpl
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import axes3d, Axes3D
from pylab import plot,subplot,axis,stem,show,figure

import numpy as np

# GroopM imports
import PCA

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
    'mer1' : tables.FloatCol(pos=1)
    'mer2' : tables.FloatCol(pos=2)
    'mer3' : tables.FloatCol(pos=3)
    ...
    
    **Coverage profile**
    table = 'coverage'
    'stoit1' : tables.FloatCol(pos=1)
    'stoit2' : tables.FloatCol(pos=2)
    'stoit3' : tables.FloatCol(pos=3)
    ...
    
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

    ** Contigs **
    table = 'contigs'
    'cid'    : tables.StringCol(512, pos=0)
    'bid'    : tables.Int32Col(pos=1)
    'length' : tables.Int32Col(pos=2)
    'core'   : tables.BoolCol(pos=3)                  # is this contig part of a bin's core?
    
    ** Bins **
    table = 'bin'
    'bid'        : tables.Int32Col(pos=0)
    'numMembers' : tables.Int32Col(pos=1)
    """
    def __init__(self): pass

#------------------------------------------------------------------------------
# DB CREATION / INITIALISATION 

    def createDB(self, bamFiles, contigs, dbFileName, kmerSize=4, dumpAll=False, force=False):
        """Main wrapper for parsing all input files"""
        # load all the passed vars
        dbFileName = dbFileName
        contigsFile = contigs
        stoitColNames = []
        
        kse = KmerSigEngine(kmerSize)
        conParser = ContigParser()
        bamParser = BamParser()

        # make sure we're only overwriting existing DBs with the users consent
        try:
            with open(dbFileName) as f:
                if(not force):
                    option = raw_input(" ****WARNING**** Database: '"+dbFileName+"' exists.\n" \
                                       " If you continue you *WILL* delete any previous analyses!\n" \
                                       " Overwrite? (y,n) : ")
                    print "****************************************************************"
                    if(option.upper() != "Y"):
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
                #------------------------
                # parse contigs and make kmer sigs
                #
                # Contig IDs are key. Any keys existing in other files but not in this file will be
                # ignored. Any missing keys in other files will be given the default profile value 
                # (typically 0). Ironically, we don't store the CIDs here, these are saved one time
                # only in the bin table 
                #------------------------
                db_desc = {}
                ppos = 0
                for mer in kse.kmerCols:
                     db_desc[mer] = tables.FloatCol(pos=ppos)
                     ppos += 1
                try:
                    KMER_table = h5file.createTable(profile_group, 'kms', db_desc, "Kmer signature")
                except:
                    print "Error creating KMERSIG table:", sys.exc_info()[0]
                    raise
                try:
                    f = open(contigsFile, "r")
                    # keep all the contig names so we can check other tables
                    # contigNames is a dict of type ID -> Length
                    contigNames = conParser.parse(f, kse, KMER_table)
                    f.close()
                except:
                    print "Could not parse contig file:",contigsFile,sys.exc_info()[0]
                    raise
                #------------------------
                # Add a table for the contigs
                #------------------------
                db_desc = {'cid' : tables.StringCol(512, pos=0),
                           'bid' : tables.Int32Col(dflt=0,pos=1),
                           'length' : tables.Int32Col(pos=2),
                           'core' : tables.BoolCol(dflt=False, pos=3) }
                try:
                    CONTIG_table = h5file.createTable(meta_group, 'contigs', db_desc, "Contig information")
                    self.initContigs(CONTIG_table, contigNames)
                except:
                    print "Error creating CONTIG table:", sys.exc_info()[0]
                    raise
                #------------------------
                # Add a table for the bins
                #------------------------
                db_desc = {'bid' : tables.Int32Col(pos=0),
                           'numMembers' : tables.Int32Col(dflt=0,pos=1) }
                try:
                    BIN_table = h5file.createTable(meta_group, 'bins', db_desc, "Bin information")
                    BIN_table.flush()
                except:
                    print "Error creating BIN table:", sys.exc_info()[0]
                    raise
                #------------------------
                # parse bam files
                #------------------------
                # build a table template based on the number of bamfiles we have
                db_desc = {}
                ppos = 0
                for bf in bamFiles:
                    # assume the file is called something like "fred.bam"
                    # we want to rip off the ".bam" part
                    bam_desc = getBamDescriptor(bf)
                    db_desc[bam_desc] = tables.FloatCol(pos=ppos)
                    stoitColNames.append(bam_desc)
                    ppos += 1
                try:
                    COV_table = h5file.createTable(profile_group, 'coverage', db_desc, "Bam based coverage")
                    bamParser.parse(bamFiles, stoitColNames, COV_table, contigNames)
                except:
                    print "Error creating coverage table:", sys.exc_info()[0]
                    raise
                #------------------------
                # Add metadata
                #------------------------
                # Create a new group under "/" (root) for storing profile information
                db_desc = {'stoitColNames' : tables.StringCol(512, pos=0),
                           'numStoits' : tables.Int32Col(pos=1),
                           'merColNames' : tables.StringCol(4096,pos=2),
                           'merSize' : tables.Int32Col(pos=2),
                           'numMers' : tables.Int32Col(pos=4),
                           'numCons' : tables.Int32Col(pos=5),
                           'numBins' : tables.Int32Col(dflt=0, pos=6),
                           'clustered' : tables.BoolCol(dflt=False, pos=7),                  # set to true after clustering is complete
                           'complete' : tables.BoolCol(dflt=False, pos=8)                    # set to true after clustering finishing is complete
                           }
                try:
                    META_table = h5file.createTable(meta_group, 'meta', db_desc, "Descriptive data")
                    self.initMeta(META_table, str.join(',',stoitColNames), len(stoitColNames), str.join(',',kse.kmerCols), kmerSize, len(kse.kmerCols), len(contigNames))
                except:
                    print "Error creating META table:", sys.exc_info()[0]
                    raise
        except:
            print "Error creating database:", dbFileName, sys.exc_info()[0]
            raise
        
        print "****************************************************************"
        print "Data loaded successfully!"
        print " ->",len(contigNames),"contigs"
        print " ->",len(stoitColNames),"BAM files"
        print "Written to: '"+dbFileName+"'"
        print "****************************************************************"

        if(dumpAll):
            self.dumpAll(dbFileName)
            
        # all good!
        return True
                
    def initContigs(self, table, contigNames):
        """Initialise the contigs table
        
        set to 0 for no bin assignment
        """
        for cid in sorted(contigNames):
            CONTIG_row = table.row
            CONTIG_row['cid'] = cid
            CONTIG_row['length'] = contigNames[cid]
            CONTIG_row.append()
        table.flush()
    
    def initMeta(self, table, stoitColNames, numStoits, merColNames, merSize, numMers, numCons):
        """Initialise the meta-data table"""
        META_row = table.row
        META_row['stoitColNames'] = stoitColNames
        META_row['numStoits'] = numStoits
        META_row['merColNames'] = merColNames
        META_row['merSize'] = merSize
        META_row['numMers'] = numMers
        META_row['numCons'] = numCons
        META_row.append()
        table.flush()
        
#------------------------------------------------------------------------------
# GET / SET DATA TABLES 

    def getConditionalIndicies(self, dbFileName, condition=''):
        """return the indicies into the db which meet the condition"""
        if('' == condition):
            condition = "cid != ''" # no condition breaks everything!
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                return np.array([x.nrow for x in h5file.root.meta.contigs.where(condition)])
        except:
            print "Error opening DB:",dbFileName, sys.exc_info()[0]
            raise

    def getCoverageProfiles(self, dbFileName, condition='', indicies=np.array([])):
        """Load coverage profiles"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                if(np.size(indicies) != 0):
                    return np.array([list(h5file.root.profile.coverage[x]) for x in indicies])
                else:
                    if('' == condition):
                        condition = "cid != ''" # no condition breaks everything!
                    return np.array([list(h5file.root.profile.coverage[x.nrow]) for x in h5file.root.meta.contigs.where(condition)])
        except:
            print "Error opening DB:",dbFileName, sys.exc_info()[0]
            raise

    def nukeBins(self, dbFileName):
        """Reset all bin information, completely"""
        print "    Clearing all old bin information from",dbFileName
        contig_names = {}
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                contig_names = dict(zip(
                                        [list(x)[0] for x in h5file.root.meta.contigs.readWhere("cid != ''")],
                                        [list(x)[2] for x in h5file.root.meta.contigs.readWhere("cid != ''")]
                                        )
                                    )
        except:
            print "Error opening DB:",dbFileName, sys.exc_info()[0]
            raise
        try:
            with tables.openFile(dbFileName, mode='a', rootUEP="/meta") as meta_group:
                # clear bin stats
                # try remove any older failed attempts
                try:
                    meta_group.removeNode('/', 'tmp_bins')
                except:
                    pass
                # make a new tmp table
                db_desc = {'bid' : tables.Int32Col(pos=0), 'numMembers' : tables.Int32Col(dflt=0,pos=1) }
                BIN_table = meta_group.createTable('/', 'tmp_bins', db_desc, "Bin information")
                # rename as the bins table
                meta_group.renameNode('/', 'bins', 'tmp_bins', overwrite=True)       

                # clear contig bin ids
                # try remove any older failed attempts
                try:
                    meta_group.removeNode('/', 'tmp_contigs')
                except:
                    pass
                # make a new tmp table
                db_desc = {'cid' : tables.StringCol(512, pos=0),
                           'bid' : tables.Int32Col(dflt=0,pos=1),
                           'length' : tables.Int32Col(pos=2),
                           'core' : tables.BoolCol(dflt=False, pos=3) }
                CONTIG_table = meta_group.createTable('/', 'tmp_contigs', db_desc, "Contig information")
                self.initContigs(CONTIG_table, contig_names)
                # do the rename
                meta_group.renameNode('/', 'contigs', 'tmp_contigs', overwrite=True)
        except:
            print "Error opening DB:",dbFileName, sys.exc_info()[0]
            raise


    def setBinStats(self, dbFileName, updates):
        """Set bins table 
        
        updates is a dictionary which looks like:
        { bid : numMembers }
        """
        try:
            with tables.openFile(dbFileName, mode='a', rootUEP="/meta") as meta_group:
                # pytables is a little "dumb" thus it's easier to 
                # make a new table and then copy everything over
                
                # try remove any older failed attempts
                try:
                    meta_group.removeNode('/', 'tmp_bins')
                except:
                    pass
                # make a new tmp table
                db_desc = {'bid' : tables.Int32Col(pos=0), 'numMembers' : tables.Int32Col(dflt=0,pos=1) }
                BIN_table = meta_group.createTable('/', 'tmp_bins', db_desc, "Bin information")
                # add in the new stuff
                for bid in updates.keys(): 
                    BIN_row = BIN_table.row
                    BIN_row['bid'] = bid
                    BIN_row['numMembers'] = updates[bid]
                    BIN_row.append()
                BIN_table.flush()
                
                # do the rename
                meta_group.renameNode('/', 'bins', 'tmp_bins', overwrite=True)
        except:
            print "Error opening DB:",dbFileName, sys.exc_info()[0]
            raise

    def getBinStats(self, dbFileName):
        """Load data from bins table
        
        Returns a dict of type:
        { bid : numMembers }
        """
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                ret_dict = {}
                all_rows = h5file.root.meta.bins.read()
                for row in all_rows:
                    ret_dict[row[0]] = row[1]
                return ret_dict
        except:
            print "Error opening DB:",dbFileName, sys.exc_info()[0]
            raise
        return {}
        
                
    def getBins(self, dbFileName, condition='', indicies=np.array([])):
        """Load per-contig bins"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                if(np.size(indicies) != 0):
                    return np.array([h5file.root.meta.contigs[x][1] for x in indicies]).ravel()
                else:
                    if('' == condition):
                        condition = "cid != ''" # no condition breaks everything!
                    return np.array([list(x)[1] for x in h5file.root.meta.contigs.readWhere(condition)]).ravel()
        except:
            print "Error opening DB:",dbFileName, sys.exc_info()[0]
            raise

    def setBins(self, dbFileName, updates):
        """Set per-contig bins
        
        updates is a dictionary which looks like:
        { tableRow : binValue }
        """
        row_nums = updates.keys()
        try:
            with tables.openFile(dbFileName, mode='a') as h5file:
                table = h5file.root.meta.contigs
                for row_num in updates.keys():
                    new_row = np.zeros((1,),dtype=('S512,i4,i4,b1'))
                    new_row[:] = [(table[row_num][0],updates[row_num],table[row_num][2],table[row_num][3])]
                    table.modifyRows(start=row_num, rows=new_row)
                table.flush()
        except:
            print "Error opening DB:",dbFileName, sys.exc_info()[0]
            raise

    def getCores(self, dbFileName, condition='', indicies=np.array([])):
        """Load bin core info"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                if(np.size(indicies) != 0):
                    return np.array([h5file.root.meta.contigs[x][3] for x in indicies]).ravel()
                else:
                    if('' == condition):
                        condition = "cid != ''" # no condition breaks everything!
                    return np.array([list(x)[3] for x in h5file.root.meta.contigs.readWhere(condition)]).ravel()
        except:
            print "Error opening DB:",dbFileName, sys.exc_info()[0]
            raise

    def setCores(self, dbFileName, updates):
        """Set bin cores
        
        updates is a dictionary which looks like:
        { tableRow : coreValue }
        """
        row_nums = updates.keys()
        try:
            with tables.openFile(dbFileName, mode='a') as h5file:
                table = h5file.root.meta.contigs
                for row_num in updates.keys():
                    new_row = np.zeros((1,),dtype=('S512,i4,i4,b1'))
                    new_row[:] = [(table[row_num][0],table[row_num][1],table[row_num][2],updates[row_num])]
                    table.modifyRows(start=row_num, rows=new_row)
                table.flush()
        except:
            print "Error opening DB:",dbFileName, sys.exc_info()[0]
            raise

    def getContigNames(self, dbFileName, condition='', indicies=np.array([])):
        """Load contig names"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                if(np.size(indicies) != 0):
                    return np.array([h5file.root.meta.contigs[x][0] for x in indicies]).ravel()
                else:
                    if('' == condition):
                        condition = "cid != ''" # no condition breaks everything!
                    return np.array([list(x)[0] for x in h5file.root.meta.contigs.readWhere(condition)]).ravel()
        except:
            print "Error opening DB:",dbFileName, sys.exc_info()[0]
            raise

    def getContigLengths(self, dbFileName, condition='', indicies=np.array([])):
        """Load contig lengths"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                if(np.size(indicies) != 0):
                    return np.array([h5file.root.meta.contigs[x][2] for x in indicies]).ravel()
                else:
                    if('' == condition):
                        condition = "cid != ''" # no condition breaks everything!
                    return np.array([list(x)[2] for x in h5file.root.meta.contigs.readWhere(condition)]).ravel()
        except:
            print "Error opening DB:",dbFileName, sys.exc_info()[0]
            raise

    def getKmerSigs(self, dbFileName, condition='', indicies=np.array([])):
        """Load kmer sigs"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                if(np.size(indicies) != 0):
                    return np.array([list(h5file.root.profile.kms[x]) for x in indicies])
                else:
                    if('' == condition):
                        condition = "cid != ''" # no condition breaks everything!
                    return np.array([list(h5file.root.profile.kms[x.nrow]) for x in h5file.root.meta.contigs.where(condition)])
        except:
            print "Error opening DB:",dbFileName, sys.exc_info()[0]
            raise

    def getMetaField(self, dbFileName, fieldName):
        """return the value of fieldName in the metadata tables"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                # theres only one value
                return h5file.root.meta.meta.read()[fieldName][0]
        except:
            print "Error opening DB:",dbFileName, sys.exc_info()[0]
            raise

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

    def getNumBins(self, dbFileName):
        """return the value of numBins in the metadata tables"""
        return self.getMetaField(dbFileName, 'numBins')
        
    def setNumBins(self, dbFileName, numBins):
        """set the number of bins"""
        try:
            with tables.openFile(dbFileName, mode='a') as h5file:
                META_table = h5file.root.meta.meta
                for META_row in META_table: # there is only one meta row
                    META_row['numBins'] = numBins
                    META_row.update()
                META_table.flush()
        except:
            print "Error opening database:", dbFileName, sys.exc_info()[0]
            raise
        
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
            print "Error opening database:", dbFileName, sys.exc_info()[0]
            raise
            
    def setClustered(self, dbFileName, state=True):
        """Set the state of clustering"""
        try:
            with tables.openFile(dbFileName, mode='a') as h5file:
                META_table = h5file.root.meta.meta
                for META_row in META_table: # there is only one meta row
                    META_row['clustered'] = state
                    META_row.update()
                META_table.flush()
        except:
            print "Error opening database:", dbFileName, sys.exc_info()[0]
            raise
            
    def isComplete(self, dbFileName):
        """Has this data set been *completely* clustered?"""
        try:
            with tables.openFile(dbFileName, mode='r') as h5file:
                return h5file.root.meta.meta.read()['complete']
        except:
            print "Error opening database:", dbFileName, sys.exc_info()[0]
            raise

    def setComplete(self, dbFileName, state=True):
        """Set the state of completion"""
        try:
            with tables.openFile(dbFileName, mode='a') as h5file:
                META_table = h5file.root.meta.meta
                for META_row in META_table: # there is only one meta row
                    META_row['complete'] = state
                    META_row.update()
                META_table.flush()
        except:
            print "Error opening database:", dbFileName, sys.exc_info()[0]
            raise

#------------------------------------------------------------------------------
# FILE / IO 

    def dumpContigs(self, table):
        """Raw dump of contig information"""
        print "-----------------------------------"
        print "Contigs table"
        print "-----------------------------------"
        for row in table:
            print row['cid'],",",row['length'],",",row['bid'],",",row['core']

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
            print "Error opening database:", dbFileName, sys.exc_info()[0]
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
                
    def parse(self, contigFile, kse, table):
        """Do the heavy lifting of parsing"""
        print "Parsing contigs"        
        tmp_storage = {} # save everything here first so we can sort accordingly
        for cid,seq,qual in self.readfq(contigFile):
            tmp_storage[cid] = (kse.getKSig(seq.upper()), len(seq)) 
        
        con_names = {}
        for cid in sorted(tmp_storage.keys()):     
            con_names[cid] = tmp_storage[cid][1]
            # make a new row
            KMER_row = table.row
            # punch in the data
            for mer in tmp_storage[cid][0].keys():
                KMER_row[mer] = tmp_storage[cid][0][mer]
            KMER_row.append()
        table.flush()
        return con_names

    def dumpTnTable(self, table, kmerCols):
        """Dump the guts of the TN table"""
        print "-----------------------------------"
        print "TNuclSig table"
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
    def __init__(self, kLen):
        self.kLen = kLen
        self.compl = string.maketrans('ACGT', 'TGCA')
        self.kmerCols = self.makeKmerColNames()
        self.numMers = len(self.kmerCols)
        
    def makeKmerColNames(self):
        """Work out the range of kmers required based on kmer length"""
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
        for mer in out_list:
            lmer = self.shiftLowLexi(mer)
            if lmer not in ret_list:
                ret_list.append(lmer)
        return ret_list
    
    def shiftLowLexi(self, seq):
        """Return the lexicographically lowest form of this sequence"""
        rseq = self.revComp(seq)
        if(seq < rseq):
            return seq
        return rseq
        
    def revComp(self, seq):
        """Return the reverse complement of a sequence"""
        return seq.translate(self.compl)[::-1]
    
    def getKSig(self, seq):
        """Work out kmer signature for a nucleotide sequence"""
        sig = dict(zip(self.kmerCols, [0.0] * self.numMers))
        ll = len(seq)
        for i in range(0,ll-self.kLen+1):
            this_mer = self.shiftLowLexi(seq[i:i+self.kLen])
            if this_mer in sig:
                sig[this_mer] += 1
        # normalise by length and return
        return dict(zip(self.kmerCols, [ X / ll for X in sig.values()]))


###############################################################################
###############################################################################
###############################################################################
###############################################################################
class BamParser:
    """Parse multiple bam files and write the output to hdf5 """

    def __init__(self): pass
    
    def parse(self, bamFiles, stoitColNames, table, contigNames):
        """Parse multiple bam files and store the results in the main DB
        
        table: a table in an open h5 file like "CID,COV_1,...,COV_n,length"
        stoitColNames: names of the COV_x columns
        """
        # parse the BAMs
        # we need to have some type of entry for each contig
        # so start by putting 0's here
        tmp_storage = {}
        num_bams = len(stoitColNames)
        for cid in contigNames.keys():
            tmp_storage[cid] = np.zeros((num_bams))

        bam_count = 0
        for bf in bamFiles:
            bam_file = None
            try:
                bam_file = pysam.Samfile(bf, 'rb')
                print "Parsing",stoitColNames[bam_count],"(",(bam_count+1),"of",num_bams,")"
                self.parseBam(bam_file, bam_count, tmp_storage, contigNames)                
                bam_count += 1
            except:
                print "Unable to open BAM file",bf,"-- did you supply a SAM file instead?"
                raise

        # go through all the contigs sorted by name and write to the DB
        rows_created = 0
        try:
            for cid in sorted(tmp_storage.keys()):
                # make a new row
                cov_row = table.row
                # punch in the data
                for i in range(0,len(stoitColNames)):
                    cov_row[stoitColNames[i]] = tmp_storage[cid][i]
                cov_row.append()
                rows_created += 1
            table.flush()
        except:
            print "Error saving results to DB"
            raise
        return rows_created

    def parseBam(self, bamFile, bamCount, storage, contigNames):
        """Parse a bam file (handle) and store the number of reads mapped"""
        for reference, length in zip(bamFile.references, bamFile.lengths):
            if(reference in contigNames): # we only care about contigs we have seen IN
                c = Counter()             # the fasta file during contig parsing
                try:
                    bamFile.fetch(reference, 0, length, callback = c )
                    num_reads = c.counts
                except ValueError as e:
                    print "Could not calculate num reads for:",reference,"in",bf,"\t",e
                    raise
                except:
                    print "Could not calculate num reads for:",reference,"in",bf, sys.exc_info()[0]
                    raise
                
                # we have already made storage for this guy above so we can gaurantee
                # there is space to save it!
    
                # we need to divide the count by the length if we are going
                # to use a normalised coverage
                storage[reference][bamCount] = float(num_reads)/float(length)
        
    def dumpCovTable(self, table, stoitColNames):
        """Dump the guts of the coverage table"""
        print "-----------------------------------"
        print "Coverage table"
        print "-----------------------------------"
        for row in table:
            for colName in stoitColNames:
                print ",",row[colName],
            print ""

class Counter:
    """AUX: Call back for counting aligned reads
    
    Used in conjunction with pysam.fetch 
    """
    counts = 0
    def __call__(self, alignment):
        self.counts += 1

def getBamDescriptor(fullPath):
    """AUX: Reduce a full path to just the file name minus extension"""
    return os.path.splitext(os.path.basename(fullPath))[0]

###############################################################################
###############################################################################
###############################################################################
###############################################################################
class ProfileManager:
    """Interacts with the groopm DataManager and local data fields
    
    Mostly a wrapper around a group of numpy arrays and a pytables quagmire
    """
    def __init__(self, dbFileName, force=False, scaleFactor=1000):
        # data
        self.dataManager = GMDataManager()  # most data is saved to hdf
        self.dbFileName = dbFileName        # db containing all the data we'd like to use
        self.condition = ""                 # condition will be supplied at loading time
        # --> NOTE: ALL of the arrays in this section are in sync
        # --> each one holds information for an individual contig 
        self.indicies = np.array([])        # indicies into the data structure based on condition
        self.covProfiles = np.array([])     # coverage based coordinates
        self.transformedCP = np.array([])   # the munged data points
        self.contigNames = np.array([])
        self.contigLengths = np.array([])
        self.contigColours = np.array([])
        self.kmerSigs = np.array([])        # raw kmer signatures
        self.binIds = np.array([])          # list of bin IDs
        self.isCore = np.array([])          # True False values
        # --> end section

        # meta                
        self.validBinIds = {}               # valid bin ids -> numMembers
        self.binnedRowIndicies = {}         # dictionary of those indicies which belong to some bin
        self.restrictedRowIndicies = {}     # dictionary of those indicies which can not be binned yet
        self.numContigs = 0                 # this depends on the condition given
        self.numStoits = 0                  # this depends on the data which was parsed

        # misc
        self.forceWriting = force           # overwrite existng values silently?
        self.scaleFactor = scaleFactor      # scale every thing in the transformed data to this dimension

    def loadData(self,
                 condition="",              # condition as set by another function
                 bids=[],                   # if this is set then only load those contigs with these bin ids
                 verbose=True,              # many to some output messages
                 silent=False,              # some to no output messages
                 loadCovProfiles=True,
                 loadKmerSigs=True,
                 makeColours=True,
                 loadContigNames=True,
                 loadContigLengths=True,
                 loadBins=False,
                 loadCores=False):
        """Load pre-parsed data"""
        # check to see if we need to override the condition
        if(len(bids) != 0):
            condition = "((bid == "+str(bids[0])+")"
            for index in range (1,len(bids)):
                condition += " | (bid == "+str(bids[index])+")"
            condition += ")"
        if(silent):
            verbose=False
        try:
            self.numStoits = self.getNumStoits()
            self.condition = condition
            if(verbose):
                print "    Loading indicies (", condition,")"
            self.indicies = self.dataManager.getConditionalIndicies(self.dbFileName, condition=condition)
            self.numContigs = len(self.indicies)
            
            if(not silent):
                print "    Working with:",self.numContigs,"contigs"

            if(loadCovProfiles):
                if(verbose):
                    print "    Loading coverage profiles"
                self.covProfiles = self.dataManager.getCoverageProfiles(self.dbFileName, indicies=self.indicies)

            if(loadKmerSigs):
                if(verbose):
                    print "    Loading kmer sigs"
                self.kmerSigs = self.dataManager.getKmerSigs(self.dbFileName, indicies=self.indicies)

                if(makeColours):
                    if(verbose):
                        print "    Creating colour profiles"
                    colourProfile = self.makeColourProfile()
                    # use HSV to RGB to generate colours
                    S = 1       # SAT and VAL remain fixed at 1. Reduce to make
                    V = 1       # Pastels if that's your preference...
                    for val in colourProfile:
                        self.contigColours = np.append(self.contigColours, [colorsys.hsv_to_rgb(val, S, V)])
                    self.contigColours = np.reshape(self.contigColours, (self.numContigs, 3))            

            if(loadContigNames):
                if(verbose):
                    print "    Loading contig names"
                self.contigNames = self.dataManager.getContigNames(self.dbFileName, indicies=self.indicies)
            
            if(loadContigLengths):
                if(verbose):
                    print "    Loading contig lengths"
                self.contigLengths = self.dataManager.getContigLengths(self.dbFileName, indicies=self.indicies)
            
            if(loadBins):
                if(verbose):
                    print "    Loading bins"
                self.binIds = self.dataManager.getBins(self.dbFileName, indicies=self.indicies)
                if(len(bids) != 0): # need to make sure we're not restricted in terms of bins
                    tmp_bids = self.getBinStats()
                    for bid in bids:
                        self.validBinIds[bid] = tmp_bids[bid]
                else:
                    self.validBinIds = self.getBinStats()

                # fix the binned indicies
                self.binnedRowIndicies = {}
                for i in range(len(self.indicies)):
                    if(self.binIds[i] != 0):
                        self.binnedRowIndicies[i] = True 

            if(loadCores):
                if(verbose):
                    print "    Loading core info"
                self.isCore = self.dataManager.getCores(self.dbFileName, indicies=self.indicies)
            
        except:
            print "Error loading DB:", self.dbFileName, sys.exc_info()[0]
            raise

    def reduceIndicies(self, deadRowIndicies):
        """purge indicies from the data structures
        
        Be sure that deadRowIndicies are sorted ascending
        """
        # strip out the other values        
        self.indicies = np.delete(self.indicies, deadRowIndicies, axis=0)
        self.covProfiles = np.delete(self.covProfiles, deadRowIndicies, axis=0)
        self.transformedCP = np.delete(self.transformedCP, deadRowIndicies, axis=0)
        self.contigNames = np.delete(self.contigNames, deadRowIndicies, axis=0)
        self.contigLengths = np.delete(self.contigLengths, deadRowIndicies, axis=0)
        self.contigColours = np.delete(self.contigColours, deadRowIndicies, axis=0)
        self.kmerSigs = np.delete(self.kmerSigs, deadRowIndicies, axis=0)
        self.binIds = np.delete(self.binIds, deadRowIndicies, axis=0)
        self.isCore = np.delete(self.isCore, deadRowIndicies, axis=0)
        
#------------------------------------------------------------------------------
# GET / SET 

    def getNumStoits(self):
        """return the value of numStoits in the metadata tables"""
        return self.dataManager.getNumStoits(self.dbFileName)
            
    def getMerColNames(self):
        """return the value of merColNames in the metadata tables"""
        return self.dataManager.getMerColNames(self.dbFileName)
            
    def getMerSize(self):
        """return the value of merSize in the metadata tables"""
        return self.dataManager.getMerSize(self.dbFileName)

    def getNumMers(self):
        """return the value of numMers in the metadata tables"""
        return self.dataManager.getNumMers(self.dbFileName)

### USE the member vars instead!
#    def getNumCons(self):
#        """return the value of numCons in the metadata tables"""
#        return self.dataManager.getNumCons(self.dbFileName)

    def getNumBins(self):
        """return the value of numBins in the metadata tables"""
        return self.dataManager.getNumBins(self.dbFileName)
        
    def setNumBins(self, numBins):
        """set the number of bins"""
        self.dataManager.setNumBins(self.dbFileName, numBins)
        
    def getStoitColNames(self):
        """return the value of stoitColNames in the metadata tables"""
        return self.dataManager.getStoitColNames(self.dbFileName)
    
    def isClustered(self):
        """Has the data been clustered already"""
        return self.dataManager.isClustered(self.dbFileName)
    
    def setClustered(self):
        """Save that the db has been clustered"""
        self.dataManager.setClustered(self.dbFileName, True)
    
    def isComplete(self):
        """Has the data been *completely* clustered already"""
        return self.dataManager.isComplete(self.dbFileName)
    
    def setComplete(self):
        """Save that the db has been completely clustered"""
        self.dataManager.setComplete(self.dbFileName, True)

    def getBinStats(self):
        """Go through all the "bins" array and make a list of unique bin ids vs number of contigs"""
        return self.dataManager.getBinStats(self.dbFileName)
    
    def saveBinIds(self, updates):
        """Save our bins into the DB"""
        self.dataManager.setBins(self.dbFileName, updates)
    
    def saveCores(self, updates):
        """Save our core flags into the DB"""
        self.dataManager.setCores(self.dbFileName, updates)

    def saveValidBinIds(self, updates):
        """Store the valid bin Ids and number of members
                
        updates is a dictionary which looks like:
        { tableRow : [bid , numMembers] }
        """
        self.dataManager.setBinStats(self.dbFileName, updates)
        self.setNumBins(len(updates.keys()))

    def updateValidBinIds(self, updates):
        """Store the valid bin Ids and number of members
        
        updates is a dictionary which looks like:
        { bid : numMembers }
        if numMembers == 0 then the bid is removed from the table
        if bid is not in the table yet then it is added
        otherwise it is updated
        """
        # get the current guys
        existing_bin_stats = self.dataManager.getBinStats(self.dbFileName)
        num_bins = self.getNumBins()
        # now update this dict
        for bid in updates.keys():
            if bid in existing_bin_stats:
                if updates[bid] == 0:
                    # remove this guy
                    del existing_bin_stats[bid]
                    num_bins -= 1
                else:
                    # update the count
                    existing_bin_stats[bid] = updates[bid]
            else:
                # new guy!
                existing_bin_stats[bid] = updates[bid]
                num_bins += 1
        
        # finally , save
        self.saveValidBinIds(existing_bin_stats)

#------------------------------------------------------------------------------
# DATA TRANSFORMATIONS 

    def transformCP(self, silent=False):
        """Do the main ransformation on the coverage profile data"""
        # Update this guy now we know how big he has to be
        # do it this way because we may apply successive transforms to this
        # guy and this is a neat way of clearing the data 
        s = (self.numContigs,3)
        self.transformedCP = np.zeros(s)
        tmp_data = np.array([])

        if(not silent):
            print "    Radial mapping"
        # first we shift the edge values accordingly and then 
        # map each point onto the surface of a hyper-sphere
        # the vector we wish to move closer to...
        radialVals = np.array([])        
        ax = np.zeros_like(self.covProfiles[0])
        ax[0] = 1
        center_vector = np.ones_like(self.covProfiles[0])
        las = self.getAngBetween(ax, center_vector)
        center_vector /= np.linalg.norm(center_vector)
        for point in self.covProfiles:
            norm = np.linalg.norm(point)
            radialVals = np.append(radialVals, norm)
            point /= np.abs(np.log(norm+1)) # make sure we're always taking a log of something greater than 1
            tmp_data = np.append(tmp_data, self.rotateVectorAndScale(point, las, center_vector, delta_max=0.25))

        # it's nice to think that we can divide through by the min
        # but we need to make sure that it's not at 0!
        min_r = np.amin(radialVals)
        if(0 == min_r):
            min_r = 1
        # reshape this guy
        tmp_data = np.reshape(tmp_data, (self.numContigs,self.numStoits))
    
        # now we use PCA to map the surface points back onto a 
        # 2 dimensional plane, thus making the data usefuller
        index = 0
        if(self.numStoits == 2):
            if(not silent):
                print "Skip dimensionality reduction (dim < 3)"
            for point in self.covProfiles:
                self.transformedCP[index,0] = tmp_data[index,0]
                self.transformedCP[index,1] = tmp_data[index,1]
                self.transformedCP[index,2] = np.log10(radialVals[index]/min_r)
                index += 1
        else:    
            # Project the points onto a 2d plane which is orthonormal
            # to the Z axis
            if(not silent):
                print "    Dimensionality reduction"
            PCA.Center(tmp_data,verbose=0)
            p = PCA.PCA(tmp_data)
            components = p.pc()
            for point in components:
                self.transformedCP[index,0] = components[index,0]
                self.transformedCP[index,1] = components[index,1]
                if(0 > radialVals[index]):
                    self.transformedCP[index,2] = 0
                else:
                    self.transformedCP[index,2] = np.log10(radialVals[index]/min_r)
                index += 1

        # finally scale the matrix to make it equal in all dimensions                
        min = np.amin(self.transformedCP, axis=0)
        max = np.amax(self.transformedCP, axis=0)
        max = max - min
        max = max / (self.scaleFactor-1)
        for i in range(0,3):
            self.transformedCP[:,i] = (self.transformedCP[:,i] -  min[i])/max[i]

    def makeColourProfile(self):
        """Make a colour profile based on ksig information"""
        ret_array = np.array([0.0]*np.size(self.indicies))
        working_data = np.array(self.kmerSigs, copy=True) 
        PCA.Center(working_data,verbose=0)
        p = PCA.PCA(working_data)
        components = p.pc()
        
        # now make the colour profile based on PC1
        index = 0
        for point in components:
            ret_array[index] = float(components[index,0])
            index += 1
        
        # normalise to fit between 0 and 1
        ret_array -= np.min(ret_array)
        ret_array /= np.max(ret_array)
        if(False):
            print ret_array
            plt.figure(1)
            plt.subplot(111)
            plt.plot(components[:,0], components[:,1], 'r.')
            plt.show()
        return ret_array
    
    def rotateVectorAndScale(self, point, las, centerVector, delta_max=0.25):
        """
        Move a vector closer to the center of the positive quadrant
        
        Find the co-ordinates of its projection
        onto the surface of a hypersphere with radius R
        
        What?...  ...First some definitions:
       
        For starters, think in 3 dimensions, then take it out to N.
        Imagine all points (x,y,z) on the surface of a sphere
        such that all of x,y,z > 0. ie trapped within the positive
        quadrant.
       
        Consider the line x = y = z which passes through the origin
        and the point on the surface at the "center" of this quadrant.
        Call this line the "main mapping axis". Let the unit vector 
        coincident with this line be called A.
       
        Now think of any other vector V also located in the positive
        quadrant. The goal of this function is to move this vector
        closer to the MMA. Specifically, if we think about the plane
        which contains both V and A, we'd like to rotate V within this
        plane about the origin through phi degrees in the direction of
        A.
        
        Once this has been done, we'd like to project the rotated co-ords 
        onto the surface of a hypersphere with radius R. This is a simple
        scaling operation.
       
        The idea is that vectors closer to the corners should be pertubed
        more than those closer to the center.
        
        Set delta_max as the max percentage of the existing angle to be removed
        """
        theta = self.getAngBetween(point, centerVector)
        A = delta_max/((las)**2)
        B = delta_max/las
        delta = 2*B*theta - A *(theta**2) # the amount to shift
        V_p = point*(1-delta) + centerVector*delta
        return V_p/np.linalg.norm(V_p)
    
    def rad2deg(self, anglein):
        return 180*anglein/np.pi

    def getAngBetween(self, P1, P2):
        """Return the angle between two points (in radians)"""
        # find the existing angle between them theta
        c = np.dot(P1,P2)/np.linalg.norm(P1)/np.linalg.norm(P2) 
        # rounding errors hurt everyone...
        if(c > 1):
            c = 1
        elif(c < -1):
            c = -1
        return np.arccos(c) # in radians

#------------------------------------------------------------------------------
# IO and IMAGE RENDERING 

    def plotTransViews(self, tag="fordens"):
        """Plot top, side and front views of the transformed data"""
        self.renderTransData(tag+"_top.png",azim = 0, elev = 90)
        self.renderTransData(tag+"_front.png",azim = 0, elev = 0)
        self.renderTransData(tag+"_side.png",azim = 90, elev = 0)

    def renderTransCPData(self, fileName="", show=True, elev=45, azim=45, all=False, showAxis=False, primaryWidth=12, primarySpace=3, dpi=300, format='png'):
        """Plot transformed data in 3D"""
        fig = plt.figure()
        if(all):
            myAXINFO = {
                'x': {'i': 0, 'tickdir': 1, 'juggled': (1, 0, 2),
                'color': (0, 0, 0, 0, 0)},
                'y': {'i': 1, 'tickdir': 0, 'juggled': (0, 1, 2),
                'color': (0, 0, 0, 0, 0)},
                'z': {'i': 2, 'tickdir': 0, 'juggled': (0, 2, 1),
                'color': (0, 0, 0, 0, 0)},
            }

            ax = fig.add_subplot(131, projection='3d')
            ax.scatter(self.transformedCP[:,0], self.transformedCP[:,1], self.transformedCP[:,2], edgecolors=self.contigColours, c=self.contigColours, marker='.')
            ax.azim = 0
            ax.elev = 0
            ax.set_xlim3d(0,self.scaleFactor)
            ax.set_ylim3d(0,self.scaleFactor)
            ax.set_zlim3d(0,self.scaleFactor)
            ax.set_xticklabels([])
            ax.set_yticklabels([])
            ax.set_zticklabels([])
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_zticks([])
            for axis in ax.w_xaxis, ax.w_yaxis, ax.w_zaxis:
                for elt in axis.get_ticklines() + axis.get_ticklabels():
                    elt.set_visible(False)
            ax.w_xaxis._AXINFO = myAXINFO
            ax.w_yaxis._AXINFO = myAXINFO
            ax.w_zaxis._AXINFO = myAXINFO
            
            ax = fig.add_subplot(132, projection='3d')
            ax.scatter(self.transformedCP[:,0], self.transformedCP[:,1], self.transformedCP[:,2], edgecolors=self.contigColours, c=self.contigColours, marker='.')
            ax.azim = 90
            ax.elev = 0
            ax.set_xlim3d(0,self.scaleFactor)
            ax.set_ylim3d(0,self.scaleFactor)
            ax.set_zlim3d(0,self.scaleFactor)
            ax.set_xticklabels([])
            ax.set_yticklabels([])
            ax.set_zticklabels([])
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_zticks([])
            for axis in ax.w_xaxis, ax.w_yaxis, ax.w_zaxis:
                for elt in axis.get_ticklines() + axis.get_ticklabels():
                    elt.set_visible(False)
            ax.w_xaxis._AXINFO = myAXINFO
            ax.w_yaxis._AXINFO = myAXINFO
            ax.w_zaxis._AXINFO = myAXINFO
            
            ax = fig.add_subplot(133, projection='3d')
            ax.scatter(self.transformedCP[:,0], self.transformedCP[:,1], self.transformedCP[:,2], edgecolors=self.contigColours, c=self.contigColours, marker='.')
            ax.azim = 0
            ax.elev = 90
            ax.set_xlim3d(0,self.scaleFactor)
            ax.set_ylim3d(0,self.scaleFactor)
            ax.set_zlim3d(0,self.scaleFactor)
            ax.set_xticklabels([])
            ax.set_yticklabels([])
            ax.set_zticklabels([])
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_zticks([])
            for axis in ax.w_xaxis, ax.w_yaxis, ax.w_zaxis:
                for elt in axis.get_ticklines() + axis.get_ticklabels():
                    elt.set_visible(False)
            ax.w_xaxis._AXINFO = myAXINFO
            ax.w_yaxis._AXINFO = myAXINFO
            ax.w_zaxis._AXINFO = myAXINFO
        else:
            ax = fig.add_subplot(111, projection='3d')
            ax.scatter(self.transformedCP[:,0], self.transformedCP[:,1], self.transformedCP[:,2], edgecolors='none', c=self.contigColours, s=2, marker='.')
            ax.azim = azim
            ax.elev = elev
            ax.set_xlim3d(0,self.scaleFactor)
            ax.set_ylim3d(0,self.scaleFactor)
            ax.set_zlim3d(0,self.scaleFactor)
            ax.set_xticklabels([])
            ax.set_yticklabels([])
            ax.set_zticklabels([])
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_zticks([])
            if(not showAxis):
                ax.set_axis_off()

        if(fileName != ""):
            try:
                if(all):
                    fig.set_size_inches(3*primaryWidth+2*primarySpace,primaryWidth)
                else:
                    fig.set_size_inches(primaryWidth,primaryWidth)            
                plt.savefig(fileName,dpi=dpi,format=format)
                plt.close(fig)
            except:
                print "Error saving image",fileName, sys.exc_info()[0]
                raise
        elif(show):
            try:
                plt.show()
                plt.close(fig)
            except:
                print "Error showing image", sys.exc_info()[0]
                raise
        del fig

###############################################################################
###############################################################################
###############################################################################
###############################################################################
