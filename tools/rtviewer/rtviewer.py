import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as anim
import os
import sys
import time
from astropy.io import fits
import calibration_utils as cal

def makeSingleListOfInts(a1, a2, a3):
	ADC1, ADC2, ADC3 = list(), list(), list()
	for i in range(len(a1)):
		ADC1.append(int(a1[i]))
		ADC2.append(int(a2[i]))
		ADC3.append(int(a3[i]))
	return ADC1 + ADC2 + ADC3

def toVolts(data):
	adjustedData = []
	REF = 5 #3.27
	for i in data:
		if (i >> 31) == 1:
			divisor = 2**31
			adjustedData.append(REF * 2 - i/divisor * REF)
		else:
			divisor = 2**31 - 1
			adjustedData.append(i/divisor * REF)
	return adjustedData

def toDB(sweepData):
	DBData = []
	for fltIdx in range(len(sweepData)):
		DBData.append(-43.5 * sweepData[fltIdx] + 24.98)
	return DBData

def numOfRows(fileName):
	hdul = fits.open(fileName)
	data = hdul[1].data
	return len(data)

def getFilePath(directory, cardinality):
	fileLoc = os.listdir(directory)
	fileLoc.sort()
	print(fileLoc[cardinality])
	
	if cardinality < len(fileLoc):
		fileName = f'{directory}/{fileLoc[cardinality]}'
		return fileName, fileLoc[-2][:-5]
	else:
		return None, None

def readData(fileName, sweepIdx, isNotCal = False):
	hdul = fits.open(fileName)
	data = hdul[1].data
	print(len(data[sweepIdx][5]))
	
	if isNotCal:
		return data[sweepIdx][0][:7], data[sweepIdx][1][:7], data[sweepIdx][2][:7], data[sweepIdx][3], data[sweepIdx][4], int(float(data[sweepIdx][5])), float(hdul[1].header[-1])
	else:
		returndata[sweepIdx][0][:7], data[sweepIdx][1][:7], data[sweepIdx][2][:7], data[sweepIdx][3], data[sweepIdx][4], int(float(data[sweepIdx][5]))

def getCalDict():
	calFileName, calFileTime = getFilePath('/home/peterson/FilterCalibrations/', -2)
	if "-4" in calFileName: pwrSetting = -10
	elif "+5" in calFileName: pwrSetting = -1
	hdul = fits.open(calFileName)
	calData = hdul[1].data
	calDict = cal.calibrationCurve(calData, pwrSetting)
	print(calDict)
	return calDict

def run():
	faxis = [(2.6 * x + 904) for x in range(21)] #some x axis array
	
	fig = plt.figure()
	ax = fig.add_subplot(111)
	#ax.set_ylim(-55, -30)
	ax.set_xlim(50,250)
	ax.grid()
	
	colorsMap = plt.cm.get_cmap('tab20', 21)
	colors = [colorsMap(i) for i in range(21)]
	
	calDict = getCalDict()
	
	fileName, fileTime = getFilePath('/home/peterson/Continuous_Sweep', -2)
	print(fileName)
	if fileName == None or fileTime == None:
		sys.exit()
	nrows = numOfRows(fileName)
	
	for sweepIdx in range(nrows):
		a1, a2, a3, time, state, freq, vlt = readData(fileName, sweepIdx, True)
		vlt = ((vlt * 1000) // 10) / 100
		adjAxis = [(2.6 * x + 904 - freq) for x in range(21)]
		combinedData = makeSingleListOfInts(a1, a2, a3)
		voltsData = toVolts(combinedData)
		dataList = cal.toDB(voltsData, calDict)
		
		#dataList = toDB(voltsData)
		
		ax.scatter(adjAxis, dataList, marker = 'x' , c = colors, s=10)
		if sweepIdx == 0: #only displays first measure of voltage/state in the sweep
			ax.annotate(f"{vlt} V", (225, -20) , ha= "center")
			ax.annotate(f"State: {state}", (225, -21), ha="center")
	ax.set_xlabel('Frequency (MHz)')
	ax.set_ylabel('Power (dBm)')
	ax.set_title(f'Spectrum at {fileTime}')
		
	def update(frame):
		ax.clear()
		#ax.set_ylim(-55, -30)
		ax.set_xlim(50,250)
		ax.grid()
		ax.set_xlabel('Frequency (MHz)')
		ax.set_ylabel('Power (dBm)')
		
		fileName, fileTime = getFilePath('/home/peterson/Continuous_Sweep/', -2)
		if fileName == None or fileTime == None:
			sys.exit()
		
		ax.set_title(f'Spectrum at {fileTime}')
		
		calDict = getCalDict()
			
		for sweepIdx in range(nrows):
			a1, a2, a3, time, state, freq, vlt = readData(fileName, sweepIdx, True)
			vlt = ((vlt * 1000) // 10) / 100
			adjAxis = [(2.6 * x + 904 - freq) for x in range(21)]
			combinedData = makeSingleListOfInts(a1, a2, a3)
			voltsData = toVolts(combinedData)
			dataList = cal.toDB(voltsData, calDict)
			
			#dataList = toDB(voltsData)
			
			ax.scatter(adjAxis, dataList, marker = 'x' , c = colors, s=10)
			if sweepIdx == 0:  #only displays first measure of voltage/state in the sweep
				ax.annotate(f"{vlt} V", (225, -20), ha= "center")
				ax.annotate(f"State: {state}", (225, -21), ha="center")
	
	v = anim.FuncAnimation(fig, update, frames=1, repeat=True, fargs=None, interval=100)
	plt.show()

run()
